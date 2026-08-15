package com.bari.app.capture

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Local on-device queue for captured photos awaiting upload, plus a
 * continuous GPS trace file per ride (used only to compute distance
 * traveled server-side — individual photos already carry their own GPS fix).
 *
 * Everything is stored under app-private external files storage so it
 * survives app restarts (e.g. if WiFi doesn't show up until later) but is
 * cleaned up automatically if the app is uninstalled.
 */
data class PhotoMeta(
    val timestamp: String,
    val latitude: Double,
    val longitude: Double,
    val accuracy: Float,
    val speed: Float,
    val bearing: Float,
) {
    fun toJson(): String = JSONObject().apply {
        put("timestamp", timestamp)
        put("latitude", latitude)
        put("longitude", longitude)
        put("accuracy", accuracy.toDouble())
        put("speed", speed.toDouble())
        put("bearing", bearing.toDouble())
    }.toString()

    companion object {
        fun fromJson(json: String): PhotoMeta {
            val o = JSONObject(json)
            return PhotoMeta(
                timestamp = o.getString("timestamp"),
                latitude = o.getDouble("latitude"),
                longitude = o.getDouble("longitude"),
                accuracy = o.optDouble("accuracy", 0.0).toFloat(),
                speed = o.optDouble("speed", 0.0).toFloat(),
                bearing = o.optDouble("bearing", 0.0).toFloat(),
            )
        }
    }
}

data class PendingPhoto(val id: String, val jpegFile: File, val meta: PhotoMeta)

object CaptureQueue {

    private fun sessionDir(context: Context, sessionId: String): File {
        val dir = File(context.getExternalFilesDir(null), "pending/$sessionId")
        dir.mkdirs()
        return dir
    }

    fun enqueuePhoto(context: Context, sessionId: String, jpegBytes: ByteArray, meta: PhotoMeta): String {
        val id = UUID.randomUUID().toString()
        val dir = sessionDir(context, sessionId)
        File(dir, "$id.jpg").writeBytes(jpegBytes)
        File(dir, "$id.json").writeText(meta.toJson())
        return id
    }

    /** Pre-allocates a (id, target jpeg file) pair for CameraX to capture
     * directly into, avoiding an extra in-memory byte-array copy for every
     * photo during a long recording session. Call [writeMeta] once capture
     * succeeds and the associated GPS fix is known. */
    fun newCaptureTarget(context: Context, sessionId: String): Pair<String, File> {
        val id = UUID.randomUUID().toString()
        val dir = sessionDir(context, sessionId)
        return id to File(dir, "$id.jpg")
    }

    fun writeMeta(context: Context, sessionId: String, id: String, meta: PhotoMeta) {
        File(sessionDir(context, sessionId), "$id.json").writeText(meta.toJson())
    }

    fun discardCapture(context: Context, sessionId: String, id: String) {
        val dir = sessionDir(context, sessionId)
        File(dir, "$id.jpg").delete()
        File(dir, "$id.json").delete()
    }

    fun listPending(context: Context, sessionId: String): List<PendingPhoto> {
        val dir = sessionDir(context, sessionId)
        return dir.listFiles { f -> f.extension == "jpg" }
            ?.mapNotNull { jpg ->
                val jsonFile = File(dir, jpg.nameWithoutExtension + ".json")
                if (!jsonFile.exists()) return@mapNotNull null
                PendingPhoto(jpg.nameWithoutExtension, jpg, PhotoMeta.fromJson(jsonFile.readText()))
            } ?: emptyList()
    }

    fun listAllPendingSessions(context: Context): List<String> {
        val root = File(context.getExternalFilesDir(null), "pending")
        return root.listFiles { f -> f.isDirectory } ?.map { it.name } ?: emptyList()
    }

    fun pendingCount(context: Context, sessionId: String): Int = listPending(context, sessionId).size

    fun deletePending(context: Context, sessionId: String, id: String) {
        val dir = sessionDir(context, sessionId)
        File(dir, "$id.jpg").delete()
        File(dir, "$id.json").delete()
    }

    // --- GPS trace (for server-side distance calculation at ride end) ---

    fun gpsTraceFile(context: Context, sessionId: String): File {
        val dir = sessionDir(context, sessionId)
        val file = File(dir, "gps_trace.csv")
        if (!file.exists()) {
            file.writeText("timestamp,latitude,longitude,accuracy,speed,bearing\n")
        }
        return file
    }

    fun appendGpsTracePoint(context: Context, sessionId: String, meta: PhotoMeta) {
        val file = gpsTraceFile(context, sessionId)
        file.appendText("${meta.timestamp},${meta.latitude},${meta.longitude},${meta.accuracy},${meta.speed},${meta.bearing}\n")
    }
}
