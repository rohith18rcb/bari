plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.bari.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.bari.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        // ONNX Runtime ships large native libs per-ABI. arm64-v8a covers
        // essentially every real phone since ~2017, which is what actually
        // matters here (APK download size has been the real bottleneck) —
        // bundling all 4 default ABIs nearly quadrupled the APK for no
        // benefit. Add "x86_64" back temporarily if testing on an emulator.
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }

    androidResources {
        noCompress += "onnx" // store the bundled model as-is, no point re-compressing it
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // Camera capture
    implementation("androidx.camera:camera-core:1.3.4")
    implementation("androidx.camera:camera-camera2:1.3.4")
    implementation("androidx.camera:camera-lifecycle:1.3.4")
    implementation("androidx.camera:camera-view:1.3.4")

    // GPS
    implementation("com.google.android.gms:play-services-location:21.3.0")

    // Background upload scheduling
    implementation("androidx.work:work-runtime-ktx:2.9.1")

    // HTTP upload (multipart) to the laptop's FastAPI ingest endpoint
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // Foreground service lifecycle helper
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // On-device inference for the live camera detection overlay (server-side
    // detection, used for actually saved/uploaded records, is unaffected —
    // this is purely for real-time visual feedback while riding).
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.19.2")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
