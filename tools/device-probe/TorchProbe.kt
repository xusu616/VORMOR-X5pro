package xusu616.vormor.probe

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.Camera
import android.graphics.SurfaceTexture
import android.os.Looper

/** Diagnostic app_process entry: use only system/root on the owned device. */
object TorchProbe {
    @JvmStatic
    fun main(arguments: Array<String>) {
        // app_process does not prepare the main Looper for standalone tools.
        Looper.prepareMainLooper()
        val threadClass = Class.forName("android.app.ActivityThread")
        val thread = threadClass.getMethod("systemMain").invoke(null)
        val context = threadClass.getMethod("getSystemContext").invoke(thread) as Context
        val resources = context.resources
        val actions = resources.getIdentifier("config_globalActionsList", "array", "android")
        val chord = resources.getIdentifier("config_enableScreenshotChord", "bool", "android")
        println("uiMode=${resources.configuration.uiMode}")
        println("powerActions=${resources.getStringArray(actions).joinToString()}")
        println("screenshotChord=${resources.getBoolean(chord)}")

        val cameras = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        for (cameraId in cameras.cameraIdList) {
            val characteristics = cameras.getCameraCharacteristics(cameraId)
            println("camera=$cameraId facing=${characteristics.get(CameraCharacteristics.LENS_FACING)} flash=${characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE)}")
        }
        if (arguments.isEmpty()) return
        require(arguments.size == 1)
        if (arguments[0].startsWith("legacy:")) {
            val id = arguments[0].removePrefix("legacy:")
            require(id in cameras.cameraIdList)
            val camera = Camera.open(id.toInt())
            val surface = SurfaceTexture(0)
            try {
                camera.setPreviewTexture(surface)
                camera.startPreview()
                val parameters = camera.parameters
                println("LEGACY_FLASH_MODES camera=$id modes=${parameters.supportedFlashModes}")
                parameters.flashMode = Camera.Parameters.FLASH_MODE_TORCH
                camera.parameters = parameters
                println("LEGACY_TORCH_BEGIN camera=$id duration=5s")
                Thread.sleep(5_000)
            } finally {
                camera.release()
                surface.release()
                println("LEGACY_TORCH_END camera=$id")
            }
            return
        }
        require(arguments[0] in cameras.cameraIdList)
        val cameraId = arguments[0]
        println("TORCH_BEGIN camera=$cameraId duration=5s")
        cameras.setTorchMode(cameraId, true)
        try {
            Thread.sleep(5_000)
        } finally {
            cameras.setTorchMode(cameraId, false)
            println("TORCH_END camera=$cameraId")
        }
    }
}
