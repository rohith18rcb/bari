package com.bari.app.detect

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import java.nio.FloatBuffer
import kotlin.math.max
import kotlin.math.min

/** One detected pothole, in the coordinate space of the *original* bitmap
 * passed to [OnDeviceDetector.detect] (already un-letterboxed) — callers
 * only need to further map this into their own view's display coordinates. */
data class LiveDetection(
    val box: RectF,
    val confidence: Float,
    /** Box area relative to the frame — the same geometric signal
     * core/severity.py uses server-side, so the live label and the
     * eventually-uploaded record's severity are consistent. */
    val relativeArea: Float,
) {
    val severity: String
        get() = when {
            relativeArea < 0.015f -> "LOW"
            relativeArea < 0.05f -> "MEDIUM"
            else -> "HIGH"
        }
}

/**
 * Runs the same YOLOv8 pothole model server-side detection uses, on-device,
 * via ONNX Runtime Mobile — for a live camera overlay only (what actually
 * gets saved/uploaded is still decided server-side on the captured photo,
 * so this and the backend can never disagree about what's "the" record —
 * this is purely a real-time preview of what the model sees).
 *
 * Model I/O (see ml/export/export_onnx.py output): input "images"
 * [1,3,INPUT_SIZE,INPUT_SIZE] float32 CHW RGB 0..1; output "output0"
 * [1,5,8400] = (cx,cy,w,h,class0_score) x 8400 candidate boxes, box
 * coordinates already decoded to INPUT_SIZE-pixel space by the exported
 * graph (standard Ultralytics ONNX export behavior).
 */
class OnDeviceDetector(context: Context) : AutoCloseable {

    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession = env.createSession(
        context.assets.open(ASSET_NAME).readBytes(),
        OrtSession.SessionOptions(),
    )
    private val inputName = session.inputNames.iterator().next()

    fun detect(bitmap: Bitmap, confidenceThreshold: Float, iouThreshold: Float = 0.45f): List<LiveDetection> {
        val letterboxed = letterbox(bitmap, INPUT_SIZE)
        val inputBuffer = toChwFloatBuffer(letterboxed.bitmap)

        val shape = longArrayOf(1, 3, INPUT_SIZE.toLong(), INPUT_SIZE.toLong())
        OnnxTensor.createTensor(env, inputBuffer, shape).use { tensor ->
            session.run(mapOf(inputName to tensor)).use { results ->
                @Suppress("UNCHECKED_CAST")
                val output = (results[0].value as Array<Array<FloatArray>>)[0] // [5][8400]
                return decode(output, letterboxed, bitmap.width, bitmap.height, confidenceThreshold, iouThreshold)
            }
        }
    }

    override fun close() {
        session.close()
    }

    // --- Preprocessing ---

    private data class Letterbox(val bitmap: Bitmap, val scale: Float, val padX: Float, val padY: Float)

    /** Resizes preserving aspect ratio and pads with YOLO's standard grey
     * (114,114,114) to reach a square [size]x[size] — matches how the
     * model was trained/exported, so boxes decode back correctly. */
    private fun letterbox(src: Bitmap, size: Int): Letterbox {
        val scale = min(size.toFloat() / src.width, size.toFloat() / src.height)
        val newW = (src.width * scale).toInt()
        val newH = (src.height * scale).toInt()
        val padX = (size - newW) / 2f
        val padY = (size - newH) / 2f

        val out = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(out)
        canvas.drawColor(android.graphics.Color.rgb(114, 114, 114))
        val scaled = Bitmap.createScaledBitmap(src, newW, newH, true)
        canvas.drawBitmap(scaled, padX, padY, Paint(Paint.FILTER_BITMAP_FLAG))
        return Letterbox(out, scale, padX, padY)
    }

    private fun toChwFloatBuffer(bitmap: Bitmap): FloatBuffer {
        val size = bitmap.width * bitmap.height
        val buffer = FloatBuffer.allocate(3 * size)
        val pixels = IntArray(size)
        bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)

        // CHW: all R, then all G, then all B — matches the model's expected input layout.
        for (c in 0..2) {
            val shift = when (c) { 0 -> 16; 1 -> 8; else -> 0 } // R, G, B byte offsets in ARGB
            for (p in pixels) {
                buffer.put(((p shr shift) and 0xFF) / 255f)
            }
        }
        buffer.rewind()
        return buffer
    }

    // --- Postprocessing: decode raw YOLO output + NMS ---

    private fun decode(
        output: Array<FloatArray>, // [5][8400]: cx,cy,w,h,score rows
        lb: Letterbox,
        origWidth: Int,
        origHeight: Int,
        confidenceThreshold: Float,
        iouThreshold: Float,
    ): List<LiveDetection> {
        val numBoxes = output[0].size
        val candidates = mutableListOf<LiveDetection>()

        for (i in 0 until numBoxes) {
            val score = output[4][i]
            if (score < confidenceThreshold) continue

            val cx = output[0][i]
            val cy = output[1][i]
            val w = output[2][i]
            val h = output[3][i]

            // Undo letterbox padding/scale to get back to original-bitmap pixel space.
            val origCx = (cx - lb.padX) / lb.scale
            val origCy = (cy - lb.padY) / lb.scale
            val origW = w / lb.scale
            val origH = h / lb.scale

            val x1 = max(0f, origCx - origW / 2)
            val y1 = max(0f, origCy - origH / 2)
            val x2 = min(origWidth.toFloat(), origCx + origW / 2)
            val y2 = min(origHeight.toFloat(), origCy + origH / 2)
            if (x2 <= x1 || y2 <= y1) continue

            val relativeArea = ((x2 - x1) * (y2 - y1)) / (origWidth.toFloat() * origHeight.toFloat())
            candidates.add(LiveDetection(RectF(x1, y1, x2, y2), score, relativeArea))
        }

        return nonMaxSuppression(candidates, iouThreshold)
    }

    private fun nonMaxSuppression(boxes: List<LiveDetection>, iouThreshold: Float): List<LiveDetection> {
        val sorted = boxes.sortedByDescending { it.confidence }.toMutableList()
        val kept = mutableListOf<LiveDetection>()
        while (sorted.isNotEmpty()) {
            val best = sorted.removeAt(0)
            kept.add(best)
            sorted.removeAll { iou(best.box, it.box) > iouThreshold }
        }
        return kept
    }

    private fun iou(a: RectF, b: RectF): Float {
        val interLeft = max(a.left, b.left)
        val interTop = max(a.top, b.top)
        val interRight = min(a.right, b.right)
        val interBottom = min(a.bottom, b.bottom)
        val interArea = max(0f, interRight - interLeft) * max(0f, interBottom - interTop)
        val union = a.width() * a.height() + b.width() * b.height() - interArea
        return if (union <= 0f) 0f else interArea / union
    }

    companion object {
        private const val ASSET_NAME = "pothole_yolo.onnx"
        private const val INPUT_SIZE = 640
    }
}
