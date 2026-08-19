package com.bari.app

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.bari.app.capture.CaptureQueue
import com.bari.app.capture.CaptureService
import com.bari.app.capture.SessionMeta
import com.bari.app.databinding.ActivityMainBinding
import com.bari.app.detect.OnDeviceDetector
import com.bari.app.net.ApiClient
import com.bari.app.upload.DetectionEvents
import com.bari.app.upload.UploadWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.Date
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private var isRiding = false

    // --- Live camera preview + on-device detection overlay: only bound
    // while riding and this activity is visible, so neither the preview nor
    // the live inference does any work in the background (capture itself,
    // and the record that actually gets saved, are entirely unaffected
    // either way — see CaptureService.rebindCamera + core/mobile_ingest.py). ---
    private var captureService: CaptureService? = null
    private var serviceBound = false
    private var onDeviceDetector: OnDeviceDetector? = null
    private val detectionExecutor = Executors.newSingleThreadExecutor()
    private val inferenceInFlight = AtomicBoolean(false)

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            val binder = service as CaptureService.LocalBinder
            captureService = binder.getService()
            serviceBound = true
            captureService?.attachPreview(binding.cameraPreview.surfaceProvider)
            binding.textPreviewHint.visibility = View.GONE
            loadDetectorAndAttach()
        }

        override fun onServiceDisconnected(name: ComponentName) {
            captureService = null
            serviceBound = false
        }
    }

    private val detectionListener = DetectionEvents.Listener { result ->
        runOnUiThread {
            binding.textLastDetection.text = if (result.detected) {
                "Last capture: ${result.potholeId} — ${((result.confidence ?: 0f) * 100).toInt()}% confidence, " +
                    "severity ${result.severity ?: "?"}, ward ${result.ward ?: "?"}"
            } else {
                "Last capture: no pothole detected"
            }
        }
    }

    private val corePermissions = buildList {
        add(Manifest.permission.CAMERA)
        add(Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) add(Manifest.permission.POST_NOTIFICATIONS)
    }.toTypedArray()

    private val requestCorePermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { results ->
        if (results.values.all { it }) {
            requestBackgroundLocationIfNeeded()
        } else {
            Toast.makeText(this, "Camera + location permissions are required to record a ride", Toast.LENGTH_LONG).show()
        }
    }

    private val requestBackgroundLocation = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) {
            Toast.makeText(this, "Background location denied — ride will only capture while the app is open", Toast.LENGTH_LONG).show()
        }
        refreshStatus()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = Prefs(this)

        binding.editServerUrl.setText(prefs.serverUrl)

        // Restore ride state — CaptureService may still be running in the
        // background from before the app was last closed.
        isRiding = prefs.isRiding
        binding.btnToggleRide.text = if (isRiding) "Stop ride" else "Start ride"

        binding.btnRequestPermissions.setOnClickListener { requestAllPermissions() }
        binding.btnToggleRide.setOnClickListener { onToggleRide() }
        binding.btnUploadNow.setOnClickListener { onUploadNow() }

        refreshStatus()
    }

    override fun onStart() {
        super.onStart()
        DetectionEvents.addListener(detectionListener)
        if (isRiding) bindToCaptureService()
    }

    override fun onStop() {
        super.onStop()
        DetectionEvents.removeListener(detectionListener)
        unbindFromCaptureService()
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
    }

    override fun onDestroy() {
        super.onDestroy()
        detectionExecutor.shutdownNow()
    }

    private fun bindToCaptureService() {
        if (serviceBound) return
        bindService(Intent(this, CaptureService::class.java), serviceConnection, Context.BIND_AUTO_CREATE)
    }

    private fun unbindFromCaptureService() {
        if (!serviceBound) return
        captureService?.detachLiveDetection()
        captureService?.detachPreview()
        unbindService(serviceConnection)
        serviceBound = false
        captureService = null
        binding.textPreviewHint.visibility = View.VISIBLE
        binding.detectionOverlay.clear()
        onDeviceDetector?.close()
        onDeviceDetector = null
    }

    /** Loading the ONNX session touches disk/does real work, so it happens
     * off the main thread; once ready, frames start flowing from
     * CaptureService's camera into [onCameraFrame]. */
    private fun loadDetectorAndAttach() {
        detectionExecutor.execute {
            val detector = try {
                OnDeviceDetector(applicationContext)
            } catch (e: Exception) {
                null // live overlay just won't appear; capture/upload are unaffected
            }
            onDeviceDetector = detector
            if (detector != null) {
                captureService?.attachLiveDetection { bitmap -> onCameraFrame(bitmap) }
            }
        }
    }

    /** Throttled: on-device YOLO inference on a phone CPU takes real time
     * (hundreds of ms), so this only ever processes one frame at a time and
     * skips any frame that arrives while the previous one is still being
     * analyzed — CaptureService's STRATEGY_KEEP_ONLY_LATEST already drops
     * backlog at the camera level, this is the analysis-side half of that. */
    private fun onCameraFrame(bitmap: Bitmap) {
        if (!inferenceInFlight.compareAndSet(false, true)) return
        detectionExecutor.execute {
            try {
                val detector = onDeviceDetector
                if (detector == null) return@execute
                val results = detector.detect(bitmap, confidenceThreshold = LIVE_CONFIDENCE_THRESHOLD)
                runOnUiThread {
                    binding.detectionOverlay.setFrameSize(bitmap.width, bitmap.height)
                    binding.detectionOverlay.show(results)
                }
            } finally {
                inferenceInFlight.set(false)
            }
        }
    }

    // --- Permissions ---

    private fun hasAllCorePermissions() = corePermissions.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasBackgroundLocation(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        return ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestAllPermissions() {
        if (!hasAllCorePermissions()) {
            requestCorePermissions.launch(corePermissions)
        } else {
            requestBackgroundLocationIfNeeded()
        }
    }

    private fun requestBackgroundLocationIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !hasBackgroundLocation()) {
            requestBackgroundLocation.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        } else {
            refreshStatus()
        }
    }

    // --- Ride control ---

    private fun onToggleRide() {
        val serverUrl = binding.editServerUrl.text.toString().trim().trimEnd('/')
        if (serverUrl.isEmpty()) {
            Toast.makeText(this, "Enter your laptop's server address first", Toast.LENGTH_SHORT).show()
            return
        }
        prefs.serverUrl = serverUrl

        if (!isRiding) {
            if (!hasAllCorePermissions()) {
                Toast.makeText(this, "Grant permissions first", Toast.LENGTH_SHORT).show()
                return
            }
            startRide(serverUrl)
        } else {
            stopRide()
        }
    }

    /** Starts the ride immediately and locally — no network round-trip is on
     * this critical path. The session id is generated on-device (same
     * format the server would generate) and synced to the server in the
     * background by [UploadWorker], possibly much later, whenever WiFi
     * becomes available. This is what makes "start ride" work with the
     * laptop completely unreachable. */
    private fun startRide(serverUrl: String) {
        val startTime = Date()
        val sessionId = SessionIds.generate(startTime)
        val startTimeIso = SessionIds.isoTimestamp(startTime)

        prefs.activeSessionId = sessionId
        CaptureQueue.writeSessionMeta(this, sessionId, SessionMeta(startTimeIso, prefs.deviceId))

        ContextCompat.startForegroundService(this, CaptureService.startIntent(this))
        isRiding = true
        prefs.isRiding = true
        binding.btnToggleRide.text = "Stop ride"
        binding.textLastDetection.text = "No detections yet this ride."
        bindToCaptureService() // shows the live preview + detection overlay immediately, since we're visible right now
        refreshStatus()

        // Best-effort immediate sync attempt, purely for faster dashboard
        // visibility — if this fails (no connection right now), the
        // periodic/WiFi upload worker retries it later. The ride is already
        // running either way.
        CoroutineScope(Dispatchers.IO).launch {
            ApiClient(serverUrl).startSession(prefs.deviceId, sessionId, startTimeIso)
        }
    }

    private fun stopRide() {
        unbindFromCaptureService()
        startService(CaptureService.stopIntent(this))
        isRiding = false
        prefs.isRiding = false
        binding.btnToggleRide.text = "Start ride"

        val sessionId = prefs.activeSessionId
        if (sessionId != null) {
            CaptureQueue.markEnded(this, sessionId)
        }
        binding.textStatus.text = "Ride stopped. Syncing to laptop…"
        UploadWorker.enqueueOneTime(this)
        refreshStatus()
    }

    private fun onUploadNow() {
        UploadWorker.enqueueOneTime(this)
        Toast.makeText(this, "Upload requested (runs when conditions allow — usually instantly on WiFi)", Toast.LENGTH_SHORT).show()
    }

    private fun refreshStatus() {
        val sessionId = prefs.activeSessionId
        val pending = sessionId?.let { CaptureQueue.pendingCount(this, it) } ?: 0
        val totalPendingSessions = CaptureQueue.listAllPendingSessions(this).size

        binding.textStatus.text = buildString {
            appendLine("Riding: $isRiding")
            appendLine("Active session: ${sessionId ?: "none"}")
            appendLine("Pending photos (this session): $pending")
            appendLine("Sessions with pending uploads: $totalPendingSessions")
            appendLine()
            appendLine("Permissions:")
            appendLine("  Camera + location: ${hasAllCorePermissions()}")
            appendLine("  Background location: ${hasBackgroundLocation()}")
        }
    }

    companion object {
        /** Slightly more lenient than the server's CONFIDENCE_THRESHOLD
         * (0.6) so the live overlay still feels responsive, while staying
         * well above the old 0.35 that was flagging non-road objects. */
        private const val LIVE_CONFIDENCE_THRESHOLD = 0.55f
    }
}
