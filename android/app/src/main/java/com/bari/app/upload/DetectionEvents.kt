package com.bari.app.upload

import com.bari.app.net.ApiClient

/**
 * In-process fan-out of upload results from [UploadWorker] to whichever
 * MainActivity instance is currently visible, so the app can show
 * "here's what the last capture found" shortly after each automatic
 * capture+upload — not frame-by-frame live detection (that would require
 * on-device inference, which isn't implemented; see
 * docs/android_deployment.md), but real feedback on a real detection
 * result, typically within seconds of the photo being taken on WiFi.
 */
object DetectionEvents {
    fun interface Listener {
        fun onResult(result: ApiClient.PhotoUploadResult)
    }

    private val listeners = mutableListOf<Listener>()

    @Synchronized
    fun addListener(listener: Listener) {
        listeners.add(listener)
    }

    @Synchronized
    fun removeListener(listener: Listener) {
        listeners.remove(listener)
    }

    @Synchronized
    fun emit(result: ApiClient.PhotoUploadResult) {
        listeners.toList().forEach { it.onResult(result) }
    }
}
