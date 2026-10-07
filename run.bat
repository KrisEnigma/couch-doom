@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"
"%ROOT%.venv\Scripts\python.exe" -m couch_doom %*
