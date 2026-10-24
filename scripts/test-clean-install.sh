#!/usr/bin/env bash
set -euo pipefail
# Runs inside a mount/user/network namespace: no source tree, device tree,
# development tools in the work folder, real HOME or host display is mounted.
op1_archive=${1:?Pass the built archive path}
op1_result=${2:-/tmp/op1-clean-result}
mkdir -p "$op1_result"
bwrap --unshare-all --die-with-parent \
  --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib /lib64 --symlink usr/bin /bin \
  --ro-bind /etc/fonts /etc/fonts --ro-bind /etc/passwd /etc/passwd --ro-bind /etc/group /etc/group --proc /proc --dev /dev --tmpfs /tmp \
  --dir /home/test --dir /run --setenv HOME /home/test --setenv XDG_RUNTIME_DIR /tmp/runtime \
  --setenv GIO_USE_VFS local --setenv GSETTINGS_BACKEND memory --setenv GTK_A11Y none --setenv GDK_BACKEND broadway --setenv BROADWAY_DISPLAY :77 \
  --setenv PYTHONPATH '' --setenv DISPLAY '' --setenv WAYLAND_DISPLAY '' \
  --ro-bind "$op1_archive" /tmp/op1.tar.gz --bind "$op1_result" /results \
  -- /usr/bin/dbus-run-session /bin/bash -c '
set -euo pipefail
mkdir -m700 /tmp/runtime
mkdir /tmp/unpacked
tar -xzf /tmp/op1.tar.gz -C /tmp/unpacked
package=(/tmp/unpacked/op1-linux-*)
gtk4-broadwayd :77 -a 127.0.0.1 -p 0 >/tmp/broadway.log 2>&1 &
op1_display_pid=$!
trap "kill $op1_display_pid 2>/dev/null || true" EXIT
"${package[0]}/install.sh" --prefix /tmp/prefix
cd /tmp
/tmp/prefix/bin/op1-linux --version
/tmp/prefix/bin/op1-linux --demo --smoke
set +e
/tmp/prefix/bin/op1-linux --read > /results/no-device.json
op1_exit=$?
set -e
[[ $op1_exit == 1 ]]
python3 -c '\''import json;assert json.load(open("/results/no-device.json"))["code"]=="device_missing"'\''
# Installed workers must import the installed package even from a different CWD.
python3 -c '\''import sys;sys.path.insert(0,"/tmp/prefix/lib/op1-linux");from op1.__main__ import main;sys.argv=["op1","--worker","read"];raise SystemExit(main())'\'' > /results/worker.json || [[ $? == 1 ]]
python3 -c '\''import json;assert json.load(open("/results/worker.json"))["code"]=="device_missing"'\''
"${package[0]}/install.sh" --prefix /tmp/prefix
python3 /tmp/prefix/lib/op1-linux/packaging/install.py --prefix /tmp/prefix --uninstall
[[ ! -e /tmp/prefix/bin/op1-linux ]]
[[ ! -e /tmp/prefix/lib/op1-linux ]]
printf "%s\n" "PASS: clean install, arbitrary CWD, GTK demo, no-device worker, upgrade and uninstall" > /results/result.txt
' > "$op1_result/log.txt" 2>&1
cat "$op1_result/result.txt"
