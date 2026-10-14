# -*- coding: utf-8 -*-
"""视频知识库 · 新程序入口。

旧入口 `src/main.py` **保持不动**，仍可独立运行（回退用）：
    venv\\Scripts\\python.exe src\\main.py
新入口：
    venv\\Scripts\\python.exe src\\app.py      （或双击 启动视频知识库.bat）
"""

import sys

from PySide6.QtWidgets import QApplication

from main_window import WorkspaceWindow


def main():
    app = QApplication(sys.argv)
    window = WorkspaceWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
