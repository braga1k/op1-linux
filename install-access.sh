#!/usr/bin/env bash
set -euo pipefail
op1_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( EUID != 0 )); then
  if [[ -t 0 ]]; then
    exec sudo /usr/bin/bash "$op1_root/install-access.sh"
  else
    exec pkexec /usr/bin/bash "$op1_root/install-access.sh"
  fi
fi
op1_rule=/etc/udev/rules.d/70-op1-linux.rules
op1_source="$op1_root/packaging/70-op1-linux.rules"
udevadm verify "$op1_source"
if [[ -e "$op1_rule" ]] && ! cmp -s "$op1_source" "$op1_rule"; then
  cp -a -- "$op1_rule" "$op1_rule.backup.$(date +%Y%m%dT%H%M%S)"
fi
install -o root -g root -m 0644 -- "$op1_source" "$op1_rule"
udevadm control --reload-rules
for op1_device in /sys/class/hidraw/hidraw*; do
  if [[ -r "$op1_device/device/uevent" ]] && [[ "$(<"$op1_device/device/uevent")" == *'HID_ID=0003:00003367:00001978'* ]]; then
    udevadm trigger --action=change "$op1_device"
  fi
done
udevadm settle --timeout=5
printf '%s\n' 'Access rule installed. If access is not active yet, unplug and reconnect the OP1.'
