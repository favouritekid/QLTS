@echo off
REM Bọc `scripts\fe-check.sh` — CỐ Ý không dựng lại lệnh docker ở đây.
REM
REM Vì sao không viết lại bằng cmd: phần đắt giá của fe-check.sh là phép
REM CHỨNG MINH container đang chạy đúng source trên máy (băm cây source ở hai
REM phía rồi so). Viết bản thứ hai bằng cmd nghĩa là có hai công thức băm phải
REM giống hệt nhau đời đời — và khi chúng lệch, phép so sẽ luôn đỏ, rồi ai đó
REM sẽ gỡ nó đi. Một bản duy nhất thì không có gì để lệch.
REM
REM Cần Git Bash (đi kèm Git for Windows). Dùng:
REM   scripts\fe-check.cmd type-check
REM   scripts\fe-check.cmd test
REM   scripts\fe-check.cmd lint
REM   scripts\fe-check.cmd build

if "%~1"=="" (
  echo Usage: %~n0 ^<npm-script^> [args...]
  echo Example: %~n0 type-check
  exit /b 64
)

where bash >nul 2>nul
if errorlevel 1 (
  echo 🔴 Khong tim thay `bash`. fe-check can Git Bash ^(Git for Windows^).
  echo    Chay truc tiep: bash scripts/fe-check.sh %*
  exit /b 66
)

bash "%~dp0fe-check.sh" %*
