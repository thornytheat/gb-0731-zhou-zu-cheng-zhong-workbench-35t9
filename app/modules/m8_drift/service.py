from app.modules.m8_drift.detection import detect


def review(balance_rows, axes):
    """疑漂工作台入口：输入偏载判级与确认车轴，输出疑漂范围和采信轴组。"""
    return detect(balance_rows, axes)
