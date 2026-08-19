// afterBuild.js — electron-builder afterAllArtifactBuild hook
// Forces white icon label text by setting the Finder window background color
// to black (alongside the background image). macOS uses text color that
// contrasts with the background color, so black → white text.

const { execSync, spawnSync } = require('child_process');
const fs   = require('fs');
const path = require('path');
const os   = require('os');

exports.default = async function (buildResult) {
  const dmgPaths = (buildResult.artifactPaths || []).filter(p => p.endsWith('.dmg'));
  if (!dmgPaths.length) { console.log('[afterBuild] No DMG found, skipping.'); return; }

  for (const dmgPath of dmgPaths) {
    console.log(`[afterBuild] Post-processing: ${path.basename(dmgPath)}`);

    const tmpDir   = fs.mkdtempSync(path.join(os.tmpdir(), 'neytreya-dmg-'));
    const rwDmg    = path.join(tmpDir, 'rw.dmg');
    const mntPoint = path.join(tmpDir, 'mnt');
    fs.mkdirSync(mntPoint, { recursive: true });

    try {
      // 1. Convert to writable UDIF
      run(`hdiutil convert "${dmgPath}" -format UDRW -o "${rwDmg}" -quiet`);

      // 2. Attach (mount) the writable DMG
      run(`hdiutil attach "${rwDmg}" -mountpoint "${mntPoint}" -nobrowse -quiet`);

      // 3. Get the volume name from the mount point
      const volName = fs.readdirSync('/Volumes').find(v =>
        fs.realpathSync(path.join('/Volumes', v)) === fs.realpathSync(mntPoint) ||
        path.join('/Volumes', v) === mntPoint
      ) || path.basename(mntPoint);

      // 4. AppleScript: open the window and set bg color to black → white labels
      const script = `
tell application "Finder"
  tell disk "${volName}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set theViewOpts to icon view options of container window
    set background color of theViewOpts to {0, 0, 0}
    delay 1
    close
  end tell
end tell
`.trim();

      const result = spawnSync('osascript', ['-e', script], { encoding: 'utf8', timeout: 20000 });
      if (result.stderr) console.warn('[afterBuild] osascript stderr:', result.stderr.trim());

      // 5. Detach
      run(`hdiutil detach "${mntPoint}" -quiet || true`);

      // 6. Convert back to compressed APFS/UDZO and replace original
      const finalDmg = dmgPath.replace('.dmg', '_patched.dmg');
      run(`hdiutil convert "${rwDmg}" -format UDZO -imagekey zlib-level=9 -o "${finalDmg}" -quiet`);
      fs.renameSync(finalDmg, dmgPath);

      console.log(`[afterBuild] ✓ White labels applied to ${path.basename(dmgPath)}`);
    } catch (err) {
      console.error('[afterBuild] Failed (non-fatal):', err.message);
      // Try to detach if still mounted
      try { run(`hdiutil detach "${mntPoint}" -quiet`); } catch (_) {}
    } finally {
      try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
    }
  }
};

function run(cmd) {
  execSync(cmd, { stdio: 'inherit', shell: true });
}
