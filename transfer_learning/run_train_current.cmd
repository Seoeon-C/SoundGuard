@echo off
cd /d C:\Users\Chan\Desktop\a\transfer_learning
set KMP_DUPLICATE_LIB_OK=TRUE
if not exist outputs mkdir outputs
C:\Users\Chan\anaconda3\envs\firstaid-gpu\python.exe -u train_beats_project.py --epochs 10 --batch-size 16 --num-workers 0 --log-every 25 > outputs\current_train.log 2> outputs\current_train.err.log
