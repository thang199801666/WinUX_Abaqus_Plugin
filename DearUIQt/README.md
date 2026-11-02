# DearUIQt

Thư viện UI Python dùng DearPyGui/native host, tổ chức API theo QtCore, QtGui,
QtWidgets. Mục tiêu là phát triển một **subset có contract rõ ràng theo Qt 6.8**,
không phải bản thay thế PySide6/PyQt đầy đủ và không đổi backend mặc định.

## Kế hoạch và trạng thái

- [ROADMAP.md](ROADMAP.md): milestone, phạm vi tương thích, khác biệt đã biết,
  điều kiện nghiệm thu và migration.
- [PERFORMANCE.md](PERFORMANCE.md): tối ưu đã đo, giới hạn benchmark và test.
- [../tests/README.md](../tests/README.md): hướng dẫn chạy hồi quy.

Thứ tự phát triển: Core/lifecycle → Model/View semantics → model transactions →
geometry/DPI → input/widgets → tài nguyên/dữ liệu lớn → tích hợp ứng dụng.
Không ưu tiên benchmark hơn tính đúng theo Qt.

## API qua Qt facades

```python
from DearUIQt.QtCore import QItemSelectionModel
from DearUIQt.QtGui import QStandardItem, QStandardItemModel

model = QStandardItemModel()
model.appendRow(QStandardItem("Example"))
selection = QItemSelectionModel(model)
selection.setCurrentIndex(model.index(0, 0), selection.ClearAndSelect)
selection.clearCurrentIndex()  # Giữ selected items.
selection.reset()              # Xóa selection/current, không phát signal.
```

Widgets dùng `DearUIQt.QtWidgets`; các namespace `core/gui/widgets/modelview`
hiện có vẫn được giữ. Khởi tạo/render widget cần GUI runtime và đúng UI thread.
Core/standard item model có thể kiểm thử độc lập không cần WinUx hoặc GPU.

## Mốc đầu đã triển khai: M1.1

Vòng đời `QItemSelectionModel`: reset im lặng, clear/current độc lập,
`modelChanged`, no-op khi gán cùng model và tháo kết nối model cũ.

```powershell
abaqus python tests/test_dearuiqt_qt_selection_lifecycle.py
abaqus python tests/test_dearuiqt_qt_selection_lifecycle_ui.py
```

M1.2a cũng đã tách **Current selection** khỏi **keyboard current index**. Cờ
`SelectCurrent`/`ToggleCurrent` thay lớp selection tương tác; muốn đổi current
index hãy gọi `setCurrentIndex()` tường minh.

```powershell
abaqus python tests/test_dearuiqt_qt_selection_current.py
```

**Migration:** nghe `model.modelReset` nếu cần tải lại UI sau reset. Không dựa
vào selectionChanged/currentChanged khi model reset. Các gap như
tree/cell selection, auto-scroll và persistent-index remapping được ghi trong
roadmap; không nên suy ra mức tương thích từ tên class.

M1.2b/c và M1.3a đã bổ sung query hàng/cột đầy đủ, range API và shared selection
hai chiều cho list/table dạng hàng. Xem roadmap để biết migration corner accessors
và setSelectionModel. Chưa nghiệm thu toàn bộ Qt.

Chạy bộ contract đã triển khai:

```powershell
abaqus python tests/run_dearuiqt_qt_contracts.py
abaqus python tests/test_dearuiqt_qt_shared_selection_ui.py
```

Oracle runtime riêng **Qt 6.8.3** đã đối chiếu **1.018 snapshot selection**, hiện
không có khác biệt; không đồng nghĩa toàn Qt tương đương. Cách chạy và phạm vi:
[../tests/QT_ORACLE.md](../tests/QT_ORACLE.md).

M2a bổ sung row/count transactions, lazy empty cells và ownership validation.
Oracle cấu trúc **229 snapshot khớp Qt 6.8.3**; tổng bộ contract **55 test đạt**.
M2 chưa hoàn tất persistent-index/selection remapping; migration ở ROADMAP.md.

M2b hiện thêm persistent-index remap/invalidation cho row/column transactions,
subtree removal/reset và basic sort: **40 snapshot Qt C++ profile khớp**, tổng
**72 contract test đạt**. PySide clear-wrapper signals khác Qt C++ được lưu riêng
và ghi rõ trong QT_ORACLE.md. Selection remapping/arbitrary moves vẫn còn gap.

M2c bổ sung selection/current remap qua insert/remove và basic sort:
**272 snapshot khớp Qt 6.8.3**, tổng **86 contract tests đạt**; GUI shared
list/table theo item qua thay đổi hàng. Move và toàn layout/column/setItem
selection lifecycle vẫn là gap; xem ROADMAP.md để biết phạm vi hiện tại.

M2d bổ sung setItem/takeItem selection lifecycle trong phạm vi đã test:
**116 snapshot khớp Qt 6.8.3**, tổng **98 contract tests đạt**. Bao gồm range
corners, subtree detach/reinsert và thứ tự layout observers; move, toàn column
API và layout hints vẫn chưa hoàn tất.

M2e bổ sung column count/convenience transactions: **130 snapshot khớp Qt 6.8.3**,
tổng **110 contract tests đạt**. Header lifecycle, mọi overload và moves vẫn
chưa được nghiệm thu; xem ROADMAP.md và tests/QT_ORACLE.md để biết phạm vi.

M2f bổ sung header data/item lifecycle: **135 snapshot khớp Qt 6.8.3**, tổng
**123 contract tests đạt**, có GUI generated headers. Default labels 1-based;
numeric/None Display/Edit data giữ đúng kiểu. Removed/replaced Python items còn
reference được detach, không mô phỏng deleted Shiboken wrapper; move/full layout
vẫn còn gap. Phạm vi và migration được ghi trong ROADMAP.md.

M2g bổ sung **custom-model move protocol**: **115 snapshot khớp Qt 6.8.3**, tổng
**137 contract tests đạt**, có GUI shared list/table. QStandardItemModel vẫn từ
chối moveRows/moveColumns như Qt; subclass custom model phải tự sửa storage giữa
begin/end. Cross-parent columns, full layout/reset và lifetime vẫn còn gap.

M2h kiểm chứng cross-parent columns (**105 snapshot**) và sửa reset observer
visibility (**9 snapshot**, tìm/sửa 4 sai khác). Tổng **153 contract tests đạt**,
có GUI reset đổi size/empty/repopulate. Vẫn là Qt subset: full layout/reentry,
unequal-row-count transfers và deleted-item lifetime chưa tương đương toàn bộ.

M2i bổ sung recursive standard-item sort/typed layout signals: **117 snapshot
khớp Qt 6.8.3**, tổng **167 contract tests đạt**, có GUI shared sort. Xem migration
cho layout handlers và QStandardItem() empty data trong ROADMAP.md. Các kiểu
QVariant/locale và toàn layout/reentry/lifetime vẫn chưa được nghiệm thu.

M2j thêm checkIndex và bounded model audits: **70 snapshot khớp Qt 6.8.3**, tổng
**180 contract tests đạt**, gồm 300 seeded mutations/audits. Qt reference fixture
qua real model tester với 0 failure; DearUIQt helper vẫn là subset test-only,
không thay thế Qt tester đầy đủ. Full model/view parity chưa được tuyên bố.

Tối ưu S1 giảm disjoint selection commit từ **2.329 → 7,31 ms** trong benchmark
2.000 ranges + 100 additions (median 5, khoảng 319x); tổng **260 tests đạt**.
State/range/signal contracts được giữ. Đây là Python bookkeeping, không phải
GUI FPS hoặc tốc độ mọi selection command; xem PERFORMANCE.md để tái lập.

Tối ưu S2 cho 500 hàng x 8 cột: **1.498 → 109 ms** (~13,7x), và 500 cột x
8 hàng: **1.663 → 114 ms** (~14,5x), median 5. Giữ range/target order và
fallback cho rectangle/combined axes; toàn bộ probe Qt hiện có và GUI regression đạt.

S3 giữ ordered corner handles của `QItemSelection.select()` đúng Qt, thay vì
dựng lại index. Benchmark 40.000 ô giảm thêm ~20–21% (median 5); probe identity
mới có 10 snapshots khớp Qt 6.8.3. Muốn refresh corners hãy lấy model.index()
mới rõ ràng; xem PERFORMANCE.md cho migration và giới hạn đo.

S4 tăng tốc `selectedRows/selectedColumns` với live Deselect/Toggle khoảng
**2,9–3,3x** ở 2.000 sections x 8 ô (median 5), dùng blocker index cục bộ
trong mỗi query. Không cache flags/selection giữa các lần gọi; Qt contracts giữ
nguyên. Đây là Python query timing, không phải GUI FPS.

S5 tính membership delta ngay khi cập nhật, bỏ bookkeeping lặp. Chọn lại vùng
40.000 ô giảm **234 → 148 ms (~1,58x)**, median 5; Deselect/Toggle cải thiện
ít hơn khi observer đọc toàn payload. Giữ exact query/signal order, kể cả parent
khác nhau; xem PERFORMANCE.md cho benchmark và phạm vi.

S6 bỏ kiểm tra corner lặp khi singleton dùng cùng một handle: đọc 40.000
singleton payload indexes giảm **388 → 246 ms (~1,58x)**; bulk row-select có
đọc signal/commit giảm **930 → 764 ms (~1,22x)**, median 5. Không cache flags
hoặc enumeration, không thay backend; toàn bộ probe Qt/GUI regression đạt.

S7 loại range không giao nhau theo tọa độ trước khi hỏi model: merge 1.000
ranges + 100 incoming disjoint nhanh hơn khoảng **14,8–15,5x** (median 5).
Probe mới có **221 snapshots khớp Qt 6.8.3**; cả 14 probe và GUI regression đạt.
Pair search vẫn bậc hai; không suy ra dense-overlap speedup hay GUI FPS.

M2k thêm `QStandardItem.setRowCount(rows)` cho child table và invisible root:
resize trong một transaction, giữ columns/lazy cells; equal/negative count là
no-op theo Qt. Probe mới **39 snapshots khớp Qt 6.8.3**; cả **15 probe** và GUI
regression đạt. Với 2.000 rows, batching giảm structural notifications từ
**4.000 xuống 2** so với lặp từng hàng; xem PERFORMANCE.md cho timing/tradeoffs.
