package xusu616.vormor.illumination

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ComponentName
import android.content.Intent
import android.graphics.SurfaceTexture
import android.hardware.Camera
import android.os.IBinder
import android.service.quicksettings.TileService
import android.util.Log
import android.widget.Toast
import java.io.IOException

@Suppress("DEPRECATION")
class TorchService : Service() {
    private var camera: Camera? = null
    private var surface: SurfaceTexture? = null

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "词典笔照明", NotificationManager.IMPORTANCE_LOW)
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == OFF) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action != ON) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (camera != null) return START_NOT_STICKY
        val stop = PendingIntent.getService(
            this, 1, Intent(this, TorchService::class.java).setAction(OFF), PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("照明开启")
            .setContentText("正在占用照明镜头；点“关闭”释放")
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "关闭", stop).build())
            .build()
        startForeground(1, notification)
        try {
            val opened = Camera.open(1)
            camera = opened
            opened.setErrorCallback { error, _ ->
                Log.e(TAG, "Camera1 illumination HAL error: $error")
                Toast.makeText(this, "照明摄像头连接中断，请重新打开照明", Toast.LENGTH_LONG).show()
                stopSelf()
            }
            val texture = SurfaceTexture(0)
            surface = texture
            opened.setPreviewTexture(texture)
            opened.startPreview()
            val parameters = opened.parameters
            val modes = parameters.supportedFlashModes
                ?: throw UnsupportedOperationException("camera1 未声明闪光灯模式")
            if (!modes.contains(Camera.Parameters.FLASH_MODE_TORCH)) {
                throw UnsupportedOperationException("camera1 未提供照明模式")
            }
            parameters.flashMode = Camera.Parameters.FLASH_MODE_TORCH
            opened.parameters = parameters
            active = true
            updateTile()
            Log.i(TAG, "Legacy camera1 illumination enabled")
        } catch (failure: RuntimeException) {
            reportHardwareFailure(failure)
        } catch (failure: IOException) {
            reportHardwareFailure(failure)
        }
        return START_NOT_STICKY
    }

    private fun reportHardwareFailure(failure: Exception) {
        Log.e(TAG, "Camera1 illumination request failed", failure)
        Toast.makeText(this, "无法打开照明：${failure.message}", Toast.LENGTH_LONG).show()
        stopSelf()
    }

    private fun updateTile() {
        TileService.requestListeningState(this, ComponentName(this, TorchTileService::class.java))
    }

    override fun onDestroy() {
        camera?.release()
        camera = null
        surface?.release()
        surface = null
        active = false
        updateTile()
        stopForeground(true)
        Log.i(TAG, "Illumination disabled and camera1 released")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ON = "xusu616.vormor.illumination.ON"
        const val OFF = "xusu616.vormor.illumination.OFF"
        private const val CHANNEL = "illumination"
        private const val TAG = "M19_Illumination"
        @Volatile var active = false
            private set
    }
}
