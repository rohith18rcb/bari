package com.bari.app

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
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
import com.bari.app.net.ApiClient
import com.bari.app.upload.DetectionEvents
import com.bari.app.upload.UploadWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.Date

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private var isRiding = false

    // --- Live camera preview: binds to CaptureService only while riding
    // and this activity is visible, so the preview never keeps the camera
    // doing extra work in the background (capture itself is unaffected
    // either way — see CaptureService.rebindCamera). ---
    private var captureService: CaptureService? = null
    private var serviceBound = false
    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            val binder = service as CaptureService.LocalBinder
            captureService = binder.getService()
            serviceBound = true
            captureService?.attachPreview(binding.cameraPreview.surfaceProvider)
            binding.textPreviewHint.visibility = View.GONE
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

    private fun bindToCaptureService() {
        if (serviceBound) return
        bindService(Intent(this, CaptureService::class.java), serviceConnection, Context.BIND_AUTO_CREATE)
    }

    private fun unbindFromCaptureService() {
        if (!serviceBound) return
        captureService?.detachPreview()
        unbindService(serviceConnection)
        serviceBound = false
        captureService = null
        binding.textPreviewHint.visibility = View.VISIBLE
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
        bindToCaptureService() // shows the live preview immediately, since we're visible right now
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
}
