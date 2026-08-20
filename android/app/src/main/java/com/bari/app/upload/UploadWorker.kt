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
import com.bari.app.capture.PendingPhoto
import com.bari.app.net.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.TimeUnit

/**
 * Syncs every locally-queued ride (across sessions that started fully
 * offline, or just haven't found WiFi yet) to the laptop's ingest API, in
 * order: (1) ensure the session exists server-side — idempotent, safe to
 * call again even if it already synced; (2) upload every queued photo, up
 * to [MAX_CONCURRENT_UPLOADS] at once (each request has real fixed
 * latency/connection overhead independent of file size, so doing several
 * in parallel meaningfully cuts total wall-clock time — especially over a
 * slower or higher-latency connection), deleting local copies on confirmed
 * success; (3) if the ride was stopped (marked "ended" locally) and every
 * photo is now uploaded, sync the end (distance/duration) and clean up the
 * now-empty local queue directory. Anything that fails at any step (server
 * unreachable, photo rejected) stays queued and is retried on the next run
 * — nothing is ever silently dropped from the phone until the server has
 * confirmed it.
 *
 * Progress is reported via WorkManager's own progress mechanism
 * (setProgress), observable from MainActivity as "N of M uploaded" even if
 * the app was reopened mid-upload — see MainActivity's WorkInfo observer.
 */
class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val prefs = Prefs(applicationContext)
        val serverUrl = prefs.serverUrl
        if (serverUrl.isBlank()) return@withContext Result.success()

        val client = ApiClient(serverUrl)
        if (!client.ping()) return@withContext Result.retry()

        val sessionIds = CaptureQueue.listAllPendingSessions(applicationContext)
        val syncedSessions = mutableSetOf<String>()
        var anyFailure = false

        // Sync sessions first (cheap, sequential — there are far fewer
        // sessions than photos) so we know which sessions' photos are safe
        // to actually upload.
        for (sessionId in sessionIds) {
            val meta = CaptureQueue.readSessionMeta(applicationContext, sessionId)
            val deviceId = meta?.deviceId ?: prefs.deviceId
            if (client.startSession(deviceId, sessionId, meta?.startTime) != null) {
                syncedSessions.add(sessionId)
            } else {
                anyFailure = true
            }
        }

        val allPending: List<Pair<String, PendingPhoto>> = syncedSessions.flatMap { sessionId ->
            CaptureQueue.listPending(applicationContext, sessionId).map { sessionId to it }
        }

        val totalCount = allPending.size
        val uploadedCount = AtomicInteger(0)
        setProgress(workDataOf(PROGRESS_UPLOADED to 0, PROGRESS_TOTAL to totalCount))

        val semaphore = Semaphore(MAX_CONCURRENT_UPLOADS)
        val anyPhotoFailed = AtomicInteger(0)

        coroutineScope {
            allPending.map { (sessionId, photo) ->
                async {
                    semaphore.withPermit {
                        val result = client.uploadPhoto(
                            sessionId, photo.jpegFile, photo.meta.timestamp,
                            photo.meta.latitude, photo.meta.longitude,
                            photo.meta.accuracy, photo.meta.speed, photo.meta.bearing,
                        )
                        if (result.ok) {
                            CaptureQueue.deletePending(applicationContext, sessionId, photo.id)
                            DetectionEvents.emit(result)
                        } else {
                            anyPhotoFailed.incrementAndGet()
                        }
                        val done = uploadedCount.incrementAndGet()
                        setProgress(workDataOf(PROGRESS_UPLOADED to done, PROGRESS_TOTAL to totalCount))
                    }
                }
            }.awaitAll()
        }
        if (anyPhotoFailed.get() > 0) anyFailure = true

        // Finalize any synced session that's been marked "ended" and now has
        // nothing left pending.
        for (sessionId in syncedSessions) {
            val stillPending = CaptureQueue.listPending(applicationContext, sessionId).isNotEmpty()
            if (CaptureQueue.isEnded(applicationContext, sessionId) && !stillPending) {
                val trace = CaptureQueue.gpsTraceFile(applicationContext, sessionId)
                if (client.endSession(sessionId, trace)) {
                    CaptureQueue.deleteSessionDir(applicationContext, sessionId)
                } else {
                    anyFailure = true
                }
            }
        }

        val output = workDataOf("uploaded_count" to uploadedCount.get())
        if (anyFailure) Result.retry() else Result.success(output)
    }

    companion object {
        private const val PERIODIC_WORK_NAME = "bari_periodic_upload"
        private const val ONE_TIME_WORK_NAME = "bari_manual_upload"
        private const val MAX_CONCURRENT_UPLOADS = 4

        const val PROGRESS_UPLOADED = "uploaded"
        const val PROGRESS_TOTAL = "total"

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

        /** Work names MainActivity observes for progress — both the manual
         * one-shot and the periodic WiFi upload can be in flight. */
        fun observableWorkNames(): List<String> = listOf(ONE_TIME_WORK_NAME, PERIODIC_WORK_NAME)
    }
}
