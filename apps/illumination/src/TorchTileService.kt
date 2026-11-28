package xusu616.vormor.illumination

import android.Manifest
import android.content.Intent
import android.content.ComponentName
import android.content.pm.PackageManager
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.util.Log

class TorchTileService : TileService() {
    override fun onTileAdded() {
        requestListeningState(this, ComponentName(this, TorchTileService::class.java))
    }
    override fun onStartListening() {
        super.onStartListening()
        qsTile?.apply {
            label = "照明"
            state = if (TorchService.active) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
            updateTile()
            Log.i("M19_IlluminationTile", "Tile refreshed: active=${TorchService.active}, state=$state")
        }
    }

    override fun onClick() {
        unlockAndRun {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                startActivityAndCollapse(Intent(this, TorchActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            } else if (TorchService.active) {
                stopService(Intent(this, TorchService::class.java))
            } else {
                startForegroundService(Intent(this, TorchService::class.java).setAction(TorchService.ON))
            }
        }
    }
}
