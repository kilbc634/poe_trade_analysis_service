; 全局变量
global rectGui := 0
global handleGui := 0
global isDragging := false
global isResizing := false
global dragStartX, dragStartY, rectX, rectY, rectW, rectH
global handleSize := 15 ; 调整手柄大小

ForceConvertToANSI(filePath) {
    FileRead, content, %filePath%
    FileDelete, %filePath%
    FileAppend, %content%, %filePath%, CP0 ; CP0 = ANSI
}

ToggleRectangleTool() {
    global rectGui, handleGui, rectX, rectY, rectW, rectH
    
    if (rectGui) {
        ; 保存并销毁矩形
        WinGetPos, rectX, rectY, rectW, rectH, ahk_id %rectGui%
        IniWrite, %rectX%, selector.ini, Rectangle, x
        IniWrite, %rectY%, selector.ini, Rectangle, y
        IniWrite, %rectW%, selector.ini, Rectangle, width
        IniWrite, %rectH%, selector.ini, Rectangle, height

        ; 強制轉成 ANSI 編碼
        ForceConvertToANSI("selector.ini")
        
        ; 销毁手柄和矩形
        Gui, Handle:Destroy
        Gui, RectGui:Destroy
        rectGui := 0
        handleGui := 0
        ; 做完即退出（非常重要，讓 Python 可以接手）
        ExitApp
    }
    CreateRectangle()
}

CreateRectangle() {
    global rectGui, handleGui

    ; 刪除舊有設定檔，強制每次都重新使用預設值
    ; FileDelete, selector.ini
    
    ; 读取配置
    IniRead, savedX, selector.ini, Rectangle, x, 100
    IniRead, savedY, selector.ini, Rectangle, y, 100
    IniRead, savedW, selector.ini, Rectangle, width, 300
    IniRead, savedH, selector.ini, Rectangle, height, 200
    
    ; 创建主矩形GUI
    Gui, RectGui:New, +AlwaysOnTop +ToolWindow -Caption +LastFound +HwndhRectGui
    Gui, Color, 3399FF ; 蓝色
    WinSet, Transparent, 150 ; 半透明
    Gui, Show, x%savedX% y%savedY% w%savedW% h%savedH% NA, RectangleOverlay
    rectGui := hRectGui
    
    ; 绘制初始手柄
    DrawHandle(savedW, savedH)
    
    ; 设置鼠标事件
    OnMessage(0x201, "WM_LBUTTONDOWN")  ; 左键按下
    OnMessage(0x202, "WM_LBUTTONUP")    ; 左键释放
    OnMessage(0x200, "WM_MOUSEMOVE")    ; 鼠标移动
    OnMessage(0x20A, "WM_MOUSEWHEEL")   ; 鼠标滚轮
}

; 绘制手柄
DrawHandle(w, h) {
    global rectGui, handleGui, handleSize
    
    ; 获取矩形位置
    WinGetPos, rectX, rectY,,, ahk_id %rectGui%
    
    ; 计算手柄位置（右下角）
    handleX := rectX + w - handleSize
    handleY := rectY + h - handleSize
    
    ; 创建手柄GUI
    Gui, Handle:New, +AlwaysOnTop +ToolWindow -Caption +E0x20 +LastFound +HwndhHandleGui
    Gui, Color, 555555 ; 深灰色
    WinSet, Transparent, 200 ; 半透明
    Gui, Show, x%handleX% y%handleY% w%handleSize% h%handleSize% NA, HandleOverlay
    handleGui := hHandleGui
}

; 更新手柄位置
UpdateHandle() {
    global rectGui, handleGui, handleSize
    
    if (!rectGui || !handleGui)
        return
    
    ; 获取矩形位置和大小
    WinGetPos, rectX, rectY, rectW, rectH, ahk_id %rectGui%
    
    ; 计算新手柄位置
    handleX := rectX + rectW - handleSize
    handleY := rectY + rectH - handleSize
    
    ; 移动手柄
    WinMove, ahk_id %handleGui%,, handleX, handleY
}

; 检查鼠标是否在调整手柄区域
IsOverResizeHandle(x, y) {
    global rectGui, handleSize
    
    WinGetPos,,, w, h, ahk_id %rectGui%
    return (x >= w - handleSize) && (y >= h - handleSize)
}

; 鼠标左键按下事件
WM_LBUTTONDOWN(wParam, lParam, msg, hwnd) {
    global rectGui, isDragging, isResizing, dragStartX, dragStartY, rectX, rectY, rectW, rectH, handleSize
    
    if (hwnd != rectGui)
        return
    
    ; 转换坐标为窗口相对坐标
    mouseX := lParam & 0xFFFF
    mouseY := lParam >> 16
    
    ; 检查是否点在调整手柄区域
    if (IsOverResizeHandle(mouseX, mouseY)) {
        isResizing := true
        
        ; 保存初始位置和尺寸
        WinGetPos, rectX, rectY, rectW, rectH, ahk_id %rectGui%
        
        ; 保存鼠标起始位置（屏幕坐标）
        CoordMode, Mouse, Screen
        MouseGetPos, dragStartX, dragStartY
    } else {
        ; 否则是拖动整个矩形
        isDragging := true
        CoordMode, Mouse, Screen
        MouseGetPos, dragStartX, dragStartY
        WinGetPos, rectX, rectY,,, ahk_id %rectGui%
    }
    
    SetCapture()
    return 0
}

; 鼠标移动事件 - 修复了拖动手柄时的尺寸计算
WM_MOUSEMOVE(wParam, lParam, msg, hwnd) {
    global rectGui, isDragging, isResizing, dragStartX, dragStartY, rectX, rectY, rectW, rectH, handleSize
    
    if (hwnd != rectGui)
        return
    
    ; 转换坐标为窗口相对坐标
    mouseX := lParam & 0xFFFF
    mouseY := lParam >> 16
    
    ; 更新光标样式
    if (IsOverResizeHandle(mouseX, mouseY)) {
        DllCall("SetCursor", "Ptr", DllCall("LoadCursor", "UInt", 0, "UInt", 32645, "Ptr")) ; IDC_SIZENWSE
    } else {
        DllCall("SetCursor", "Ptr", DllCall("LoadCursor", "UInt", 0, "UInt", 32512, "Ptr")) ; IDC_ARROW
    }
    
    ; 处理拖动
    if (isDragging) {
        CoordMode, Mouse, Screen
        MouseGetPos, currentX, currentY
        
        ; 计算移动距离（使用浮点运算确保精度）
        deltaX := currentX - dragStartX
        deltaY := currentY - dragStartY
        
        ; 计算新位置
        newX := rectX + deltaX
        newY := rectY + deltaY
        
        ; 移动矩形
        WinMove, ahk_id %rectGui%,, newX, newY
        
        ; 更新手柄位置
        UpdateHandle()
        
        ; 更新初始位置（连续拖动）
        dragStartX := currentX
        dragStartY := currentY
        rectX := newX
        rectY := newY
        
        return 0
    }
    
    ; 处理大小调整 - 修复关键计算
    if (isResizing) {
        CoordMode, Mouse, Screen
        MouseGetPos, currentX, currentY
        
        ; 计算精确的尺寸变化量
        deltaX := currentX - dragStartX
        deltaY := currentY - dragStartY
        
        ; 计算新尺寸（保持左上角位置不变）
        newW := Max(30, rectW + deltaX)
        newH := Max(30, rectH + deltaY)
        
        ; 更新窗口大小
        WinMove, ahk_id %rectGui%,, rectX, rectY, newW, newH
        
        ; 更新手柄位置
        UpdateHandle()
        
        ; 更新初始尺寸和鼠标位置（连续调整）
        rectW := newW
        rectH := newH
        dragStartX := currentX
        dragStartY := currentY
        
        return 0
    }
    return 0
}

; 鼠标左键释放事件
WM_LBUTTONUP(wParam, lParam, msg, hwnd) {
    global isDragging, isResizing
    
    if (hwnd = rectGui) {
        isDragging := false
        isResizing := false
        ReleaseCapture()
    }
    return 0
}

; 鼠标滚轮事件 - 调整透明度
WM_MOUSEWHEEL(wParam, lParam, msg, hwnd) {
    global rectGui
    
    if (hwnd != rectGui)
        return
    
    ; 获取滚轮方向
    wheelDelta := (wParam >> 16) > 0x7FFF ? -(0x10000 - (wParam >> 16)) : (wParam >> 16)
    
    ; 获取当前透明度
    WinGet, currentTrans, Transparent, ahk_id %rectGui%
    currentTrans := currentTrans = "" ? 255 : currentTrans
    
    ; 计算新透明度 (范围 30-255)
    newTrans := Min(255, Max(30, currentTrans + wheelDelta/120*10))
    
    ; 设置新透明度
    WinSet, Transparent, %newTrans%, ahk_id %rectGui%
    return 0
}

SetCapture() {
    global rectGui
    DllCall("SetCapture", "Ptr", rectGui)
}

ReleaseCapture() {
    DllCall("ReleaseCapture")
}

Max(a, b) {
    return a > b ? a : b
}

Min(a, b) {
    return a < b ? a : b
}

; 不保存，直接取消操作
CancelRectangleTool() {
    global rectGui, handleGui
    
    if (rectGui) {  
        ; 销毁手柄和矩形
        Gui, Handle:Destroy
        Gui, RectGui:Destroy
        rectGui := 0
        handleGui := 0
        ; 做完即退出（非常重要，讓 Python 可以接手）
        ExitApp
    }
}

ToggleRectangleTool()

; 设置热键 F3 触发矩形工具
F3::ToggleRectangleTool()
^F3::CancelRectangleTool()

; ; --------------------------
; ; Python 會用參數呼叫 AHK
; ; --------------------------
; if (A_Args.Length() >= 1) {
;     action := A_Args[1]

;     if (action = "toggle") {
;         ToggleRectangleTool()
;     }
;     ; else if (action = "cancel") {
;     ;     CancelRectangleTool()
;     ; }
; }
