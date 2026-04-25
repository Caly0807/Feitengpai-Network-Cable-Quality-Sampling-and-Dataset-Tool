@echo off
cd /d "%~dp0"

REM 把 SSH_TARGET 改成飞腾派控制通道 IP。
REM 不要填待测网线上的 IP，否则坏线会直接让 SSH 断开。
set SSH_TARGET=user@192.168.137.10
set GATEWAY_IP=192.168.10.1
set IFACE=eth0
set OUT_DIR=data\raw\dataset_pc_pi_router
set OPERATOR=your_name

set PYTHON_CMD=python
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
  set PYTHON_CMD="%LocalAppData%\Programs\Python\Python313\python.exe"
)
python -c "import sys" >nul 2>nul
if errorlevel 1 (
  %PYTHON_CMD% -c "import sys" >nul 2>nul
  if errorlevel 1 (
    set PYTHON_CMD=py -3
    py -3 -c "import sys" >nul 2>nul
    if errorlevel 1 (
      echo 没有找到可用的 Python。请先安装 Python 3，或者修复 py 启动器，然后重新运行本文件。
      pause
      exit /b 1
    )
  )
)

%PYTHON_CMD% "tools\pc_collect_cable_dataset.py" ^
  --ssh-target "%SSH_TARGET%" ^
  --gateway-ip "%GATEWAY_IP%" ^
  --iface "%IFACE%" ^
  --out "%OUT_DIR%" ^
  --operator "%OPERATOR%" ^
  --topology "pi_router_gateway" ^
  --skip-iperf ^
  --skip-udp ^
  --samples-per-cable 5 ^
  --plan "data\plans\sampling_plan_template.csv"
pause
