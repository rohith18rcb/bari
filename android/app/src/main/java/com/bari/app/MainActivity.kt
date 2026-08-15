package com.bari.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.work.WorkManager
import com.bari.app.capture.CaptureQueue
import com.bari.app.capture.CaptureService
import com.bari.app.databinding.ActivityMainBinding
import com.bari.app.net.ApiClient
import com.bari.app.upload.UploadWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private var isRiding = false

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

        binding.btnRequestPermissions.setOnClickListener { requestAllPermissions() }
        binding.btnToggleRide.setOnClickListener { onToggleRide() }
        binding.btnUploadNow.setOnClickListener { onUploadNow() }

        refreshStatus()
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
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
            stopRide(serverUrl)
        }
    }

    private fun startRide(serverUrl: String) {
        binding.textStatus.text = "Starting ride…"
        CoroutineScope(Dispatchers.IO).launch {
            val client = ApiClient(serverUrl)
            val sessionId = client.startSession(prefs.deviceId)
            withContext(Dispatchers.Main) {
                if (sessionId == null) {
                    binding.textStatus.text = "Could not reach $serverUrl.\nCheck the address and that your phone is on the same WiFi as the laptop, or start the ride offline (capture still queues locally)."
                    prefs.activeSessionId = "OFFLINE-" + System.currentTimeMillis()
                } else {
                    prefs.activeSessionId = sessionId
                }
                ContextCompat.startForegroundService(this@MainActivity, CaptureService.startIntent(this@MainActivity))
                isRiding = true
                binding.btnToggleRide.text = "Stop ride"
                refreshStatus()
            }
        }
    }

    private fun stopRide(serverUrl: String) {
        startService(CaptureService.stopIntent(this))
        isRiding = false
        binding.btnToggleRide.text = "Start ride"

        val sessionId = prefs.activeSessionId
        binding.textStatus.text = "Ride stopped. Uploading remaining photos…"
        UploadWorker.enqueueOneTime(this)

        if (sessionId != null && !sessionId.startsWith("OFFLINE-")) {
            CoroutineScope(Dispatchers.IO).launch {
                val trace = CaptureQueue.gpsTraceFile(this@MainActivity, sessionId)
                ApiClient(serverUrl).endSession(sessionId, trace)
                withContext(Dispatchers.Main) { refreshStatus() }
            }
        }
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
