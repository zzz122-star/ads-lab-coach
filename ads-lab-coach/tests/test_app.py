from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_flow():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.sidebar.text_input[0].set_value("tester").run()
    assert not at.exception
    assert len(at.metric) == 3
    for page in ["故障诊断", "知识卡片", "小组进度"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, page


def test_all_experiments_render():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.text_input[0].set_value("tester").run()
    assert not at.exception
    titles = list(at.selectbox[0].options)
    assert len(titles) == 5
    for title in titles:
        at.selectbox[0].set_value(title).run()
        assert not at.exception, title


def test_step_checkbox_persists():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.text_input[0].set_value("stepper").run()
    at.sidebar.checkbox[0].uncheck().run()
    assert not at.exception
    assert len(at.checkbox) == 7  # 6 个步骤勾选 + 侧栏自动检测开关
    at.checkbox[0].check().run()
    assert not at.exception
    assert at.checkbox[0].value is True


def test_lab2_uses_original_guide_controls():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.text_input[0].set_value("layout-tester").run()
    title = next(t for t in at.selectbox[0].options if "实验 2" in t)
    at.selectbox[0].select(title).run()
    assert not at.exception
    assert len(at.metric) == 5
    assert {b.label for b in at.button} >= {"重新开始", "按现有文件重新检测"}
    assert len([c for c in at.checkbox if c.label == "我已完成这一步"]) == 5
    assert len(at.radio) == 2  # sidebar navigation and the original confirm checkpoint
    headers = {h.value for h in at.subheader}
    assert {"操作步骤", "预期结果", "演示讲稿", "检查点（结果自动判定）"} <= headers
    assert "实验 2 自动验证" not in headers
    assert not any(s.label == "固定监测的设计（不会随最近编辑的其他设计切换）" for s in at.selectbox)
    at.number_input(key="exp02_transmission_line_f0_ghz").set_value(2.).run()
    assert not at.exception
    assert any("F=2 GHz" in m.value for m in at.markdown)
    at.button(key="exp02_transmission_line_rescan").click().run()
    assert not at.exception
    at.button(key="exp02_transmission_line_reset").click().run()
    assert not at.exception
