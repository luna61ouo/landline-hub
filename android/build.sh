#!/bin/bash
# Build the phone app without Gradle: aapt2 + javac + d8 + apksigner.
#   ANDROID_HOME   Android SDK (needs platforms/android-35 and build-tools/35.0.0)
#   KEYSTORE       signing keystore (default: keystore/release.jks, created on first build)
#   KS_PASS_FILE   file holding the keystore password (default: keystore/password, created on first build)
# Keep the keystore safe: without it you cannot ship updates to installed phones.
# Output: build/landline-hub.apk
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
: "${ANDROID_HOME:?set ANDROID_HOME to your Android SDK}"
ANDROID_JAR="$ANDROID_HOME/platforms/android-35/android.jar"
BT="$ANDROID_HOME/build-tools/35.0.0"
KEYSTORE="${KEYSTORE:-$ROOT/keystore/release.jks}"
KS_PASS_FILE="${KS_PASS_FILE:-$ROOT/keystore/password}"
mkdir -p "$(dirname "$KEYSTORE")" "$(dirname "$KS_PASS_FILE")"
if [ ! -f "$KS_PASS_FILE" ]; then
  umask 077; head -c 24 /dev/urandom | base64 | tr -d '/+=' > "$KS_PASS_FILE"
  echo "created $KS_PASS_FILE"
fi
KS_PASS=$(cat "$KS_PASS_FILE")
rm -rf build && mkdir -p build/gen build/classes
"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link --manifest AndroidManifest.xml --min-sdk-version 29 --target-sdk-version 35 \
  --auto-add-overlay -I "$ANDROID_JAR" -R build/res.zip --java build/gen -o build/app-no-dex.apk
find src build/gen -name '*.java' | sort > build/srclist.txt
javac --release 11 -d build/classes -classpath "$ANDROID_JAR" @build/srclist.txt
find build/classes -name '*.class' > build/classlist.txt
"$BT/d8" --release --output build/ --min-api 29 @build/classlist.txt
( cd build && zip -q -j app-no-dex.apk classes.dex && mv app-no-dex.apk app-unsigned.apk )
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -keystore "$KEYSTORE" -alias app -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$KS_PASS" -keypass "$KS_PASS" -dname "CN=landline-hub" >/dev/null 2>&1
  echo "created $KEYSTORE"
fi
"$BT/zipalign" -f -p 4 build/app-unsigned.apk build/app-aligned.apk
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
  --out build/landline-hub.apk build/app-aligned.apk
"$BT/apksigner" verify build/landline-hub.apk
echo "APK: $ROOT/build/landline-hub.apk"
