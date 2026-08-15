package com.bari.app

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.random.Random

/** Generates session ids in the same SES-yyyyMMdd-HHmmss-XXXX format the
 * backend uses (core/ids.py::generate_session_id) — the app creates its own
 * id locally so a ride can start with zero network dependency; the id is
 * synced to the server later (see ApiClient.startSession). */
object SessionIds {
    private const val HEX = "0123456789ABCDEF"

    fun generate(startTime: Date = Date()): String {
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(startTime)
        val suffix = (1..4).map { HEX[Random.nextInt(HEX.length)] }.joinToString("")
        return "SES-$stamp-$suffix"
    }

    fun isoTimestamp(date: Date = Date()): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("Asia/Kolkata")
        return fmt.format(date)
    }
}
