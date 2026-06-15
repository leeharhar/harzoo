# 安装与启动

=== "Windows"

    !!! tip "小提示：如何使用电脑上的PowerShell来操控电脑？"
        大部分用户都习惯使用鼠标点击来操控电脑，但还有另一种方式来操控电脑，就是使用电脑上自带的**PowerShell**软件，通过在**PowerShell**中执行文字命令来操控电脑（即：在PowerShell中输入对应的文字命令，然后按回车执行）。Harzoo的安装与启动，均需要通过此方式进行。

    **Step 1. 打开 PowerShell**

    `PowerShell`软件是电脑自带的，和其他常用的软件一样，直接搜索 `PowerShell`， 即可看到`Windows PowerShell`，并启动。

    **Step 2. 检查 Python是否已安装**

    运行以下命令查看Python的版本

    ```powershell
    python --version
    ```

    - 若显示 `Python 3.10.0` 或更高，跳到步骤 3。
    - 若未安装或版本过低，请为你的电脑先安装Python，请点击 [python-3.13.14-amd64.exe](https://mirrors.huaweicloud.com/python/3.13.14/python-3.13.14-amd64.exe) 下载Python安装包，一步步点击安装（安装过程中需要勾选 `Add python.exe to PATH`选项）。

    **Step 3. 安装 Harzoo**

    ```powershell
    python -m pip install harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```


    或

    ```powershell
    pip install harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

    **Step 4. 启动**

    ```powershell
    harzoo
    ```

    启动后，会提示缺少配置文件之类的错误，这是正常现象，稍后按照 [**「配置与使用」**](/config/) 章节进行配置即可正常使用了。

    **Step 5. 更新 Harzoo**（可选）

    ```powershell
    python -m pip install --upgrade harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

    或

    ```powershell
    pip install --upgrade harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

=== "macOS"

    !!! tip "小提示：如何使用电脑上的终端软件来操控电脑？"
        大部分用户都习惯使用鼠标点击来操控电脑，但还有另一种方式来操控电脑，就是使用电脑上自带的**终端**软件，通过在**终端**中执行文字命令来操控电脑（即：在终端中输入对应的文字命令，然后按回车执行）。Harzoo的安装与启动，均需要通过此方式进行。

    **Step 1. 打开终端软件**

    `终端`软件是电脑自带的，和其他常用的软件一样，直接搜索 `终端` 即可找到，并启动。

    **Step 2. 检查 Python是否已安装**

    运行以下命令查看Python的版本

    ```bash
    python3 --version
    ```

    - 若显示 `Python 3.10.0` 或更高，跳到步骤 3。
    - 若未安装或版本过低，请为你的电脑先安装Python，请点击 [python-3.13.14-macos11.pkg](https://mirrors.huaweicloud.com/python/3.13.14/python-3.13.14-macos11.pkg) 下载Python安装包，进行安装。

    **Step 3. 安装 Harzoo**

    ```bash
    python3 -m pip install harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

    或

    ```bash
    pip3 install harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

    **Step 4. 启动**

    ```bash
    harzoo
    ```

    启动后，会提示缺少配置文件之类的错误，这是正常现象，稍后按照 [**「配置与使用」**](/config/) 章节进行配置即可正常使用了。

    **Step 5. 更新 Harzoo**（可选）

    ```bash
    python3 -m pip install --upgrade harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

    或

    ```bash
    pip3 install --upgrade harzoo -i https://pypi.tuna.tsinghua.edu.cn/simple
    ```

=== "Linux"

    **Step 1. 打开终端**

    **Step 2. 检查 Python是否已安装**

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

    **Step 3. 安装 Harzoo**

    ```bash
    python3 -m pip install harzoo
    ```

    或

    ```bash
    pip3 install harzoo
    ```

    **Step 4. 启动**

    ```bash
    harzoo
    ```

    启动后，会提示缺少配置文件之类的错误，这是正常现象，稍后按照 [**「配置与使用」**](/config/) 章节进行配置即可正常使用了。

    **Step 5. 更新 Harzoo**（可选）

    ```bash
    python3 -m pip install --upgrade harzoo
    ```

    或

    ```bash
    pip3 install --upgrade harzoo
    ```

---


