package com.bari.app.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Thin client for the BARI laptop dashboard's mobile ingest API
 * (dashboard/ingest.py). All calls are blocking (OkHttp .execute()) —
 * callers (CaptureService's background thread, UploadWorker's doWork()) are
 * already off the main thread.
 */
class ApiClient(private val baseUrl: String) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    /** Returns the new session_id, or null on failure. */
    fun startSession(deviceId: String): String? {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("device_id", deviceId)
            .build()
        val request = Request.Builder().url("$baseUrl/api/mobile/session/start").post(body).build()
        client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) return null
            val json = JSONObject(resp.body?.string() ?: return null)
            return json.optString("session_id", null.toString()).takeIf { it != "null" }
        }
    }

    data class PhotoUploadResult(val ok: Boolean, val detected: Boolean, val potholeId: String?)

    fun uploadPhoto(
        sessionId: String, jpegFile: File, timestamp: String,
        latitude: Double, longitude: Double, accuracy: Float, speed: Float, bearing: Float,
    ): PhotoUploadResult {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", jpegFile.name, jpegFile.asRequestBody("image/jpeg".toMediaType()))
            .addFormDataPart("timestamp", timestamp)
            .addFormDataPart("latitude", latitude.toString())
            .addFormDataPart("longitude", longitude.toString())
            .addFormDataPart("accuracy", accuracy.toString())
            .addFormDataPart("speed", speed.toString())
            .addFormDataPart("bearing", bearing.toString())
            .build()
        val request = Request.Builder().url("$baseUrl/api/mobile/session/$sessionId/photo").post(body).build()
        return try {
            client.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) return PhotoUploadResult(false, false, null)
                val json = JSONObject(resp.body?.string() ?: "{}")
                PhotoUploadResult(true, json.optBoolean("detected", false), json.optString("pothole_id", null.toString()).takeIf { it != "null" })
            }
        } catch (e: Exception) {
            PhotoUploadResult(false, false, null)
        }
    }

    fun endSession(sessionId: String, gpsTraceCsv: File): Boolean {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("gps_trace", gpsTraceCsv.name, gpsTraceCsv.asRequestBody("text/csv".toMediaType()))
            .build()
        val request = Request.Builder().url("$baseUrl/api/mobile/session/$sessionId/end").post(body).build()
        return try {
            client.newCall(request).execute().use { it.isSuccessful }
        } catch (e: Exception) {
            false
        }
    }

    fun ping(): Boolean {
        val request = Request.Builder().url("$baseUrl/api/stats").get().build()
        return try {
            client.newCall(request).execute().use { it.isSuccessful }
        } catch (e: Exception) {
            false
        }
    }
}
