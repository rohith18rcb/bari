package com.bari.app

import android.content.Context

/** Small SharedPreferences wrapper: laptop server URL + the active ride's session id. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("bari_prefs", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString(KEY_SERVER_URL, "") ?: ""
        set(value) = sp.edit().putString(KEY_SERVER_URL, value).apply()

    var activeSessionId: String?
        get() = sp.getString(KEY_SESSION_ID, null)
        set(value) = sp.edit().putString(KEY_SESSION_ID, value).apply()

    /** Persisted (not just in-memory) so the UI correctly shows "riding" —
     * and reattaches the live camera preview — if the app is reopened while
     * CaptureService is still running in the background. */
    var isRiding: Boolean
        get() = sp.getBoolean(KEY_IS_RIDING, false)
        set(value) = sp.edit().putBoolean(KEY_IS_RIDING, value).apply()

    var deviceId: String
        get() {
            var id = sp.getString(KEY_DEVICE_ID, null)
            if (id == null) {
                id = "android-" + java.util.UUID.randomUUID().toString().take(8)
                sp.edit().putString(KEY_DEVICE_ID, id).apply()
            }
            return id
        }
        set(value) = sp.edit().putString(KEY_DEVICE_ID, value).apply()

    companion object {
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_SESSION_ID = "active_session_id"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_IS_RIDING = "is_riding"
    }
}
