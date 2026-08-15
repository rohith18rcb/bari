package com.bari.app

import android.app.Application
import com.bari.app.upload.UploadWorker

class BariApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        UploadWorker.schedulePeriodicWifiUpload(this)
    }
}
