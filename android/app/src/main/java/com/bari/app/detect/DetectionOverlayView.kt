package com.bari.app.detect

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View

/**
 * Transparent overlay drawn on top of the camera PreviewView: a yellow box
 * around each live on-device detection, labeled with confidence + the same
 * LOW/MEDIUM/HIGH severity heuristic the backend uses. This is a real-time
 * *preview* of what the on-device model sees on the current frame — the
 * record that actually gets saved/uploaded is still decided server-side
 * when a photo is captured (see docs/android_deployment.md).
 *
 * [setFrameSize] must be called once the source bitmap size is known (the
 * detector reports boxes in that bitmap's pixel space); this view then
 * scales them to however it's actually laid out on screen, assuming the
 * PreviewView above/below it uses FIT_CENTER (so the mapping is a uniform
 * scale, not a crop).
 */
class DetectionOverlayView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null,
) : View(context, attrs) {

    private var detections: List<LiveDetection> = emptyList()
    private var frameWidth = 0
    private var frameHeight = 0

    private val boxPaint = Paint().apply {
        color = Color.parseColor("#FFD400") // yellow
        style = Paint.Style.STROKE
        strokeWidth = 6f
        isAntiAlias = true
    }
    private val labelBgPaint = Paint().apply {
        color = Color.parseColor("#CC1A1A1A")
        style = Paint.Style.FILL
    }
    private val labelTextPaint = Paint().apply {
        color = Color.parseColor("#FFD400")
        textSize = 34f
        isAntiAlias = true
        isFakeBoldText = true
    }

    fun setFrameSize(width: Int, height: Int) {
        frameWidth = width
        frameHeight = height
    }

    fun show(results: List<LiveDetection>) {
        detections = results
        invalidate()
    }

    fun clear() {
        detections = emptyList()
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (frameWidth == 0 || frameHeight == 0 || detections.isEmpty()) return

        // Uniform FIT_CENTER mapping from frame pixel space to this view's space.
        val scale = minOf(width.toFloat() / frameWidth, height.toFloat() / frameHeight)
        val offsetX = (width - frameWidth * scale) / 2f
        val offsetY = (height - frameHeight * scale) / 2f

        for (d in detections) {
            val mapped = RectF(
                d.box.left * scale + offsetX,
                d.box.top * scale + offsetY,
                d.box.right * scale + offsetX,
                d.box.bottom * scale + offsetY,
            )
            canvas.drawRect(mapped, boxPaint)

            val widthPx = (d.box.width()).toInt()
            val heightPx = (d.box.height()).toInt()
            val label = "POTHOLE ${(d.confidence * 100).toInt()}%  ${d.severity}  ~${widthPx}x${heightPx}px"
            val textWidth = labelTextPaint.measureText(label)
            val labelTop = maxOf(0f, mapped.top - 40f)
            canvas.drawRect(mapped.left, labelTop, mapped.left + textWidth + 16f, labelTop + 40f, labelBgPaint)
            canvas.drawText(label, mapped.left + 8f, labelTop + 29f, labelTextPaint)
        }
    }
}
