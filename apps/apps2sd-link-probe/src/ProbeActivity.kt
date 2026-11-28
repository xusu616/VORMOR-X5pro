package xusu616.vormor.apps2sdprobe

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File
import java.io.IOException
import java.time.Instant

/** Only this probe's private preferences and files are used. */
class ProbeActivity : Activity() {
    private lateinit var output: TextView
    private lateinit var probeFile: File
    private var launchCount = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val preferences = getSharedPreferences("link_probe", MODE_PRIVATE)
        launchCount = preferences.getLong("launch_count", 0L) + 1L
        check(preferences.edit().putLong("launch_count", launchCount).commit()) {
            "Cannot persist the probe launch count"
        }
        probeFile = File(filesDir, "apps2sd-probe.txt")

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (16 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        content.addView(TextView(this).apply {
            text = "Apps2SD 链接与重启验证"
            textSize = 23f
        })
        output = TextView(this).apply {
            textSize = 17f
            setTextIsSelectable(true)
        }
        content.addView(output)
        content.addView(Button(this).apply {
            text = "追加一条测试记录"
            setOnClickListener {
                try {
                    probeFile.appendText("启动 $launchCount 的记录：${Instant.now()}\n")
                    showState()
                } catch (error: IOException) {
                    output.text = "写入失败，测试文件没有被清理：${error.message}"
                    Log.e(TAG, "Probe private-file write failed", error)
                }
            }
        })
        content.addView(Button(this).apply {
            text = "重新读取"
            setOnClickListener { showState() }
        })
        content.addView(TextView(this).apply {
            text = "只链接这个验证应用。重启后计数应增加，已有测试记录应保留。"
            textSize = 15f
        })
        setContentView(ScrollView(this).apply { addView(content) })

        try {
            if (!probeFile.exists()) {
                probeFile.writeText("首次测试记录：${Instant.now()}\n")
            }
            showState()
        } catch (error: IOException) {
            output.text = "测试文件读写失败：${error.message}"
            Log.e(TAG, "Probe private-file initialization failed", error)
        }
    }

    private fun showState() {
        try {
            val contents = probeFile.readText()
            val actualPath = probeFile.canonicalPath
            output.text = "启动计数：$launchCount\n\n" +
                "文件实际路径：\n$actualPath\n\n" +
                "APK 路径：\n${applicationInfo.sourceDir}\n\n" +
                "测试文件内容：\n$contents"
            Log.i(TAG, "launchCount=$launchCount file=$actualPath bytes=${probeFile.length()}")
        } catch (error: IOException) {
            output.text = "启动计数：$launchCount\n读取测试文件失败：${error.message}"
            Log.e(TAG, "Probe private-file read failed", error)
        }
    }

    companion object {
        private const val TAG = "Apps2SDLinkProbe"
    }
}
