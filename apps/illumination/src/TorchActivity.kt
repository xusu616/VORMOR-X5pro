package xusu616.vormor.illumination

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class TorchActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (20 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        layout.addView(TextView(this).apply {
            text = "M19_X6 照明\n\n使用原厂照明通道。开灯会占用照明所在的镜头，关灯后释放。可在快捷设置中添加“照明”磁贴。"
            textSize = 18f
        })
        layout.addView(Button(this).apply {
            text = "打开照明"
            setOnClickListener {
                if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(arrayOf(Manifest.permission.CAMERA), 1)
                } else {
                    startForegroundService(Intent(this@TorchActivity, TorchService::class.java).setAction(TorchService.ON))
                }
            }
        })
        layout.addView(Button(this).apply {
            text = "关闭照明"
            setOnClickListener { stopService(Intent(this@TorchActivity, TorchService::class.java)) }
        })
        setContentView(layout)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startForegroundService(Intent(this, TorchService::class.java).setAction(TorchService.ON))
        }
    }
}
