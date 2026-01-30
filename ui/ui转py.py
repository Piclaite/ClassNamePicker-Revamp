import os
wjm=str(input("ui文件路径："))
pywjm=str(input("生成的py文件路径："))
pyui5lj=r'D:\Python031402\Scripts\pyuic5.exe'
pyui5lj=str(input(r"pyuic5路径（默认D:\Python031402\Scripts\pyuic5.exe）：") or pyui5lj )
os.system(f"{pyui5lj} -o {pywjm} {wjm}")