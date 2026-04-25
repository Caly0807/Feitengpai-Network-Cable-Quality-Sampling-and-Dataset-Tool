@echo off
setlocal

if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"

if not exist "%USERPROFILE%\.ssh\id_ed25519.pub" (
  echo Creating SSH key...
  ssh-keygen -t ed25519 -N "" -f "%USERPROFILE%\.ssh\id_ed25519"
)

echo.
echo Installing public key to user@192.168.10.35
echo Type the Phytium Pi password once if asked.
type "%USERPROFILE%\.ssh\id_ed25519.pub" | ssh user@192.168.10.35 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"

echo.
echo Testing key login...
ssh user@192.168.10.35 "echo SSH key OK"

echo.
pause
