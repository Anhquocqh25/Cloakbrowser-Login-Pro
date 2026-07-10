__all__ = ["MainWindow"]


def __getattr__(name: str):
    if name == "MainWindow":
        from ui.main_window import MainWindow
        return MainWindow
    raise AttributeError(name)
