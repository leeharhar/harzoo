# 安装与启动

=== "Windows"

    1. **打开 PowerShell**（按 `Win + R`，输入 `powershell`进行搜索）
    2. **检查 Python是否已安装**

        运行以下命令查看版本

        ```powershell
        python --version
        ```

        - 若显示 `Python 3.10.0` 或更高，跳到步骤 3。
        - 若未安装或版本过低，请点击 [python-3.13.14-amd64.exe](https://mirrors.huaweicloud.com/python/3.13.14/python-3.13.14-amd64.exe) 下载安装包，**勾选 `Add python.exe to PATH`** 后安装。

    3. **安装 Harzoo**

        ```powershell
        python -m pip install harzoo
        ```

        或

        ```powershell
        pip install harzoo
        ```

    4. **启动**

        ```powershell
        harzoo
        ```

    5. **更新 Harzoo**（可选）

        ```powershell
        python -m pip install --upgrade harzoo
        ```

        或

        ```powershell
        pip install --upgrade harzoo
        ```

=== "macOS"

    1. **打开终端**（`Command + 空格` → `Terminal`）
    2. **检查 Python是否已安装**：

        运行以下命令查看版本

        ```bash 
        python3 --version
        ```

        - 若显示 `Python 3.10.0` 或更高，跳到步骤 3。
        - 若未安装或版本过低，请点击 [python-3.13.14-macos11.pkg](https://mirrors.huaweicloud.com/python/3.13.14/python-3.13.14-macos11.pkg) 下载安装包并安装。

    3. **安装 Harzoo**

        ```bash
        python3 -m pip install harzoo
        ```

        或

        ```bash
        pip3 install harzoo
        ```

    4. **启动**

        ```bash
        harzoo
        ```

    5. **更新 Harzoo**（可选）

        ```bash
        python3 -m pip install --upgrade harzoo
        ```

        或

        ```bash
        pip3 install --upgrade harzoo
        ```

=== "Linux"

    1. **打开终端**（`Ctrl + Alt + T`）
    2. **检查 Python是否已安装**：
    
        运行以下命令查看版本

        ```bash
        python3 --version
        ```

        - 若显示 `Python 3.10.0` 或更高，跳到步骤 3。
        - 若未安装或版本过低，先安装 Python：

        ```bash
        sudo apt update
        sudo apt install -y python3 python3-pip
        ```

    3. **安装 Harzoo**

        ```bash
        python3 -m pip install harzoo
        ```

        或

        ```bash
        pip3 install harzoo
        ```

    4. **启动**

        ```bash
        harzoo
        ```

    5. **更新 Harzoo**（可选）

        ```bash
        python3 -m pip install --upgrade harzoo
        ```

        或

        ```bash
        pip3 install --upgrade harzoo
        ```

---

安装框架后，务必先完成 **「配置与使用」** 章节中的配置包步骤，再启动。
