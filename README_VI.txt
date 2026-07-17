WINUX ABAQUS/CAE PLUG-IN 1.1
============================

Cài đặt
-------
1. Copy nguyên thư mục WinUX_Abaqus_Plugin vào:
   %APPDATA%\abaqus_plugins\
2. Xóa phiên bản cũ trước khi copy.
3. Khởi động lại Abaqus/CAE.
4. Chọn Plug-ins -> WinUX Explorer...

Yêu cầu
-------
WinUX chạy bằng một bản Python 3 độc lập có tkinter. Không sử dụng Python/SMApy
đi kèm Abaqus vì runtime đó có thể không hỗ trợ Tkinter và các biến môi trường
của nó có thể gây lỗi import io.

Kiểm tra Python chuẩn:
    py -3 -m tkinter

Nếu cửa sổ tkinter xuất hiện thì Python phù hợp.

Nếu plug-in không tự tìm thấy Python, tạo biến môi trường:
    WINUX_PYTHON=C:\Users\<user>\AppData\Local\Programs\Python\Python313\pythonw.exe

Không đặt WINUX_PYTHON tới thư mục SIMULIA, Abaqus, SMApy hoặc EstProducts.

Sửa lỗi trong 1.1
-----------------
- Không còn dùng AFXForm.getFirstDialog() trả về None.
- Dùng FOX command handler để click menu mở WinUX trực tiếp.
- Loại bỏ fallback sang sys.executable của Abaqus.
- Làm sạch PYTHONHOME/PYTHONPATH trước khi mở Python ngoài.
- Kiểm tra tkinter trước khi khởi chạy giao diện.
