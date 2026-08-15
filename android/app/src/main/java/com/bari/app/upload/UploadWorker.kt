package com.bari.app.upload

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.bari.app.Prefs
import com.bari.app.capture.CaptureQueue
import com.bari.app.net.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * Uploads every queued photo (across all sessions with pending files) to the
 * laptop's ingest API. Deletes local copies on confirmed success; anything
 * that fails (server unreachable, photo rejected) stays queued and is
 * retried on the next run — nothing is ever silently dropped on the phone.
 */
class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val prefs = Prefs(applicationContext)
        val serverUrl = prefs.serverUrl
        if (serverUrl.isBlank()) return@withContext Result.success()

        val client = ApiClient(serverUrl)
        if (!client.ping()) return@withContext Result.retry()

        var anyFailure = false
        var uploadedCount = 0

        for (sessionId in CaptureQueue.listAllPendingSessions(applicationContext)) {
            if (sessionId.startsWith("OFFLINE-")) continue // no server session was ever created for this ride
            for (photo in CaptureQueue.listPending(applicationContext, sessionId)) {
                val result = client.uploadPhoto(
                    sessionId, photo.jpegFile, photo.meta.timestamp,
                    photo.meta.latitude, photo.meta.longitude,
                    photo.meta.accuracy, photo.meta.speed, photo.meta.bearing,
                )
                if (result.ok) {
                    CaptureQueue.deletePending(applicationContext, sessionId, photo.id)
                    uploadedCount++
                } else {
                    anyFailure = true
                }
            }
        }

        val output = workDataOf("uploaded_count" to uploadedCount)
        if (anyFailure) Result.retry() else Result.success(output)
    }

    companion object {
        private const val PERIODIC_WORK_NAME = "bari_periodic_upload"
        private const val ONE_TIME_WORK_NAME = "bari_manual_upload"

        /** Manual "Upload now": tries over whatever connection is available right now. */
        fun enqueueOneTime(context: Context) {
            val request = OneTimeWorkRequestBuilder<UploadWorker>().build()
            WorkManager.getInstance(context).enqueueUniqueWork(ONE_TIME_WORK_NAME, ExistingWorkPolicy.REPLACE, request)
        }

        /** Automatic background upload — WiFi/unmetered only, per the app's "queue on phone,
         * upload later on WiFi" design (never spends mobile data on photo uploads). */
        fun schedulePeriodicWifiUpload(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.UNMETERED)
                .build()
            val request = PeriodicWorkRequestBuilder<UploadWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC_WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
