package com.bari.app.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.location.Location
import android.os.Binder
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.graphics.Bitmap
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.UseCase
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import com.bari.app.MainActivity
import com.bari.app.Prefs
import com.bari.app.R
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicInteger

/**
 * Foreground service: keeps the camera + GPS alive while the phone is in a
 * pocket / screen off, periodically taking a geotagged photo and queuing it
 * for upload (see CaptureQueue, UploadWorker). A persistent notification is
 * required by Android for any service that runs camera/location work in the
 * background — there is no way around showing it, by design of the platform.
 *
 * Capture is triggered by distance-or-time, whichever comes first: a photo
 * is taken once the phone has moved MIN_CAPTURE_DISTANCE_M since the last
 * shot, or MAX_CAPTURE_INTERVAL_MS have elapsed with no shot (covers the
 * "stopped at a traffic light for a while" case without spamming photos).
 */
class CaptureService : LifecycleService() {

    private lateinit var prefs: Prefs
    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private var cameraProvider: ProcessCameraProvider? = null
    private var imageCapture: ImageCapture? = null
    private var preview: Preview? = null
    private var imageAnalysis: ImageAnalysis? = null
    private var onLiveFrame: ((Bitmap) -> Unit)? = null
    private lateinit var cameraExecutorThread: HandlerThread
    private lateinit var cameraExecutor: Handler

    /** Lets a bound, foregrounded MainActivity show what the capture camera
     * is currently seeing. Purely a UI convenience — capture keeps running
     * via [imageCapture] whether or not anything is bound to watch it. */
    inner class LocalBinder : Binder() {
        fun getService(): CaptureService = this@CaptureService
    }
    private val binder = LocalBinder()

    override fun onBind(intent: Intent): IBinder {
        super.onBind(intent)
        return binder
    }

    fun attachPreview(surfaceProvider: Preview.SurfaceProvider) {
        preview = Preview.Builder().build().also { it.setSurfaceProvider(surfaceProvider) }
        rebindCamera()
    }

    fun detachPreview() {
        preview = null
        rebindCamera()
    }

    /** Streams decoded RGBA bitmaps from the live camera feed to [onFrame],
     * for on-device inference (see MainActivity + OnDeviceDetector). Only
     * the latest frame is ever queued (STRATEGY_KEEP_ONLY_LATEST) — if
     * inference is slower than the camera's frame rate, frames are dropped
     * rather than backing up, which is exactly what a "live-ish" (not
     * frame-perfect) overlay wants. */
    fun attachLiveDetection(onFrame: (Bitmap) -> Unit) {
        onLiveFrame = onFrame
        imageAnalysis = ImageAnalysis.Builder()
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
            .also { analysis ->
                analysis.setAnalyzer(Executor { command -> cameraExecutor.post(command) }) { imageProxy: ImageProxy ->
                    try {
                        onLiveFrame?.invoke(rgba8888ToBitmap(imageProxy))
                    } catch (e: Exception) {
                        // A single bad frame must never take capture/GPS down with it.
                    } finally {
                        imageProxy.close()
                    }
                }
            }
        rebindCamera()
    }

    fun detachLiveDetection() {
        imageAnalysis?.clearAnalyzer()
        imageAnalysis = null
        onLiveFrame = null
        rebindCamera()
    }

    private var sessionId: String? = null
    private var lastCaptureLocation: Location? = null
    private var lastCaptureTimeMs: Long = 0
    private var captureInFlight = false
    private val capturedCount = AtomicInteger(0)

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val location = result.lastLocation ?: return
            onNewLocation(location)
        }
    }

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)
        cameraExecutorThread = HandlerThread("bari-camera").apply { start() }
        cameraExecutor = Handler(cameraExecutorThread.looper)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_STOP -> {
                stopRide()
                return START_NOT_STICKY
            }
            else -> startRide()
        }
        return START_STICKY
    }

    private fun startRide() {
        sessionId = prefs.activeSessionId
        if (sessionId == null) {
            stopSelf()
            return
        }
        startForeground(NOTIFICATION_ID, buildNotification(0))
        startLocationUpdates()
        startCamera()
    }

    private fun stopRide() {
        fusedLocationClient.removeLocationUpdates(locationCallback)
        cameraProvider?.unbindAll()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutorThread.quitSafely()
    }

    // --- Location ---

    private fun startLocationUpdates() {
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, LOCATION_INTERVAL_MS).build()
        try {
            fusedLocationClient.requestLocationUpdates(request, locationCallback, Looper.getMainLooper())
        } catch (e: SecurityException) {
            // Permissions not granted; MainActivity is responsible for requesting them
            // before starting this service, but fail safe rather than crash.
            stopSelf()
        }
    }

    private fun onNewLocation(location: Location) {
        val sid = sessionId ?: return
        val meta = PhotoMeta(
            timestamp = isoTimestamp(location.time),
            latitude = location.latitude,
            longitude = location.longitude,
            accuracy = location.accuracy,
            speed = if (location.hasSpeed()) location.speed else 0f,
            bearing = if (location.hasBearing()) location.bearing else 0f,
        )
        CaptureQueue.appendGpsTracePoint(this, sid, meta)

        val distanceSinceLast = lastCaptureLocation?.distanceTo(location) ?: Float.MAX_VALUE
        val timeSinceLast = System.currentTimeMillis() - lastCaptureTimeMs
        val shouldCapture = !captureInFlight &&
            (distanceSinceLast >= MIN_CAPTURE_DISTANCE_M || timeSinceLast >= MAX_CAPTURE_INTERVAL_MS)

        if (shouldCapture) {
            lastCaptureLocation = location
            lastCaptureTimeMs = System.currentTimeMillis()
            capturePhoto(sid, meta)
        }
    }

    // --- Camera ---

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            cameraProvider = future.get()
            // Full sensor resolution (often 12MP+) is pure waste here: the
            // detector's own input is 640x640, and every extra pixel is
            // extra upload bandwidth over what's often a slow/metered
            // connection. ~1280x960 is comfortably more detail than the
            // model uses while cutting typical JPEG size by 5-10x.
            val resolutionSelector = androidx.camera.core.resolutionselector.ResolutionSelector.Builder()
                .setResolutionStrategy(
                    androidx.camera.core.resolutionselector.ResolutionStrategy(
                        android.util.Size(1280, 960),
                        androidx.camera.core.resolutionselector.ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                    ),
                )
                .build()
            imageCapture = ImageCapture.Builder()
                .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                .setResolutionSelector(resolutionSelector)
                .setJpegQuality(80)
                .build()
            if (!rebindCamera()) stopSelf() // initial bind failing is fatal — no capture is possible at all
        }, mainExecutor())
    }

    /** (Re)binds whichever use cases currently apply — capture always,
     * preview/analysis only while a MainActivity is bound and watching.
     * Called both on initial setup and whenever [attachPreview]/[detachPreview]
     * or [attachLiveDetection]/[detachLiveDetection] change what should be
     * bound. Returns false if the bind failed. */
    private fun rebindCamera(): Boolean {
        val provider = cameraProvider ?: return false
        val capture = imageCapture ?: return false
        return try {
            provider.unbindAll()
            val useCases = mutableListOf<UseCase>(capture)
            preview?.let { useCases.add(it) }
            imageAnalysis?.let { useCases.add(it) }
            provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, *useCases.toTypedArray())
            true
        } catch (e: Exception) {
            false
        }
    }

    /** Converts a single-plane RGBA_8888 ImageAnalysis frame (requested via
     * ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888) directly into a Bitmap —
     * that format's per-pixel byte layout (R,G,B,A) matches what
     * Bitmap.Config.ARGB_8888 expects from copyPixelsFromBuffer. */
    private fun rgba8888ToBitmap(image: ImageProxy): Bitmap {
        val plane = image.planes[0]
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val rowPadding = rowStride - pixelStride * image.width
        val bitmap = Bitmap.createBitmap(image.width + rowPadding / pixelStride, image.height, Bitmap.Config.ARGB_8888)
        bitmap.copyPixelsFromBuffer(plane.buffer)
        return if (rowPadding == 0) bitmap else Bitmap.createBitmap(bitmap, 0, 0, image.width, image.height)
    }

    private fun mainExecutor() = androidx.core.content.ContextCompat.getMainExecutor(this)

    private fun capturePhoto(sid: String, meta: PhotoMeta) {
        val capture = imageCapture ?: return
        captureInFlight = true
        val (id, targetFile) = CaptureQueue.newCaptureTarget(this, sid)
        val outputOptions = ImageCapture.OutputFileOptions.Builder(targetFile).build()

        capture.takePicture(
            outputOptions,
            Executor { command -> cameraExecutor.post(command) },
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    CaptureQueue.writeMeta(this@CaptureService, sid, id, meta)
                    captureInFlight = false
                    val count = capturedCount.incrementAndGet()
                    updateNotification(count)
                }

                override fun onError(exception: ImageCaptureException) {
                    CaptureQueue.discardCapture(this@CaptureService, sid, id)
                    captureInFlight = false
                }
            },
        )
    }

    // --- Notification ---

    private fun buildNotification(count: Int): Notification {
        val channelId = "bari_capture"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(channelId, getString(R.string.notification_channel_name), NotificationManager.IMPORTANCE_LOW)
            manager.createNotificationChannel(channel)
        }
        val tapIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, channelId)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText("Photos captured this ride: $count")
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentIntent(tapIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(count: Int) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(count))
    }

    private fun isoTimestamp(epochMs: Long): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("Asia/Kolkata")
        return fmt.format(Date(epochMs))
    }

    companion object {
        const val ACTION_STOP = "com.bari.app.action.STOP"
        private const val NOTIFICATION_ID = 42
        private const val LOCATION_INTERVAL_MS = 2000L
        private const val MIN_CAPTURE_DISTANCE_M = 10f
        private const val MAX_CAPTURE_INTERVAL_MS = 8000L

        fun startIntent(context: Context): Intent = Intent(context, CaptureService::class.java)
        fun stopIntent(context: Context): Intent = Intent(context, CaptureService::class.java).setAction(ACTION_STOP)
    }
}
