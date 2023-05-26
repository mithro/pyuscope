#!/usr/bin/env python3

from uscope.gui.gstwidget import gstwidget_main
from uscope.util import add_bool_arg
from uscope import config
import json
import json5
from collections import OrderedDict

from PyQt5 import Qt
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

import os.path
import sys
import traceback
import threading
import importlib.util

from uscope.app.argus.common import ArgusCommon, ArgusShutdown, error

from uscope.app.argus.widgets import MainTab, ImagerTab, BatchImageTab, AdvancedTab, StitchingTab


class FullscreenVideo(QWidget):
    def __init__(self, widget):
        super().__init__()
        self.setWindowTitle("pyuscope fullscreen")
        layout = QVBoxLayout()
        layout.addWidget(widget)
        layout.setAlignment(Qt.AlignCenter)
        self.setLayout(layout)
        self.showMaximized()


class MainWindow(QMainWindow):
    def __init__(self, microscope=None, verbose=False):
        QMainWindow.__init__(self)
        self.verbose = verbose
        self.ac = None
        self.awidgets = OrderedDict()
        self.polli = 0
        self.ac = ArgusCommon(microscope_name=microscope, mw=self)
        self.init_objects()
        self.ac.logs.append(self.mainTab.log)
        self.initUI()
        self.post_ui_init()
        # save for plugin load
        self.cachej = None
        plugin_name = os.getenv("PYUSCOPE_TAB_PLUGIN")
        if plugin_name:
            self.load_tab_plugin(plugin_name)

    def __del__(self):
        self.shutdown()

    def cache_load(self):
        fn = self.ac.aconfig.cache_fn()
        self.cachej = {}
        if os.path.exists(fn):
            with open(fn, "r") as f:
                self.cachej = json5.load(f)
        for tab in self.awidgets.values():
            tab.cache_load(self.cachej)

    def cache_save(self):
        if not self.ac:
            return
        cachej = {}
        for tab in self.awidgets.values():
            tab.cache_save(cachej)
        fn = self.ac.aconfig.cache_fn()
        with open(fn, "w") as f:
            json.dump(cachej,
                      f,
                      sort_keys=True,
                      indent=4,
                      separators=(",", ": "))

    def shutdown(self):
        self.cache_save()
        for tab in self.awidgets.values():
            tab.shutdown()
        try:
            if self.ac:
                self.ac.shutdown()
        except AttributeError:
            pass

    def init_objects(self):
        # Tabs
        self.mainTab = MainTab(ac=self.ac, parent=self)
        self.awidgets["Main"] = self.mainTab
        self.imagerTab = ImagerTab(ac=self.ac, parent=self)
        self.awidgets["Imager"] = self.imagerTab
        self.batchTab = BatchImageTab(ac=self.ac, parent=self)
        self.awidgets["Batch"] = self.batchTab
        self.advancedTab = AdvancedTab(ac=self.ac, parent=self)
        self.awidgets["Advanced"] = self.advancedTab
        self.stitchingTab = StitchingTab(ac=self.ac, parent=self)
        self.awidgets["CloudStitch"] = self.stitchingTab
        self.ac.mainTab = self.mainTab
        self.ac.stitchingTab = self.stitchingTab
        self.ac.batchTab = self.batchTab
        self.pluginTab = None

    def createMenuBar(self):
        self.exitAction = QAction("Exit", self)
        self.zoomPlus = QAction("ROI zoom +", self)
        self.zoomMinus = QAction("ROI zoom -", self)
        self.fullShow = QAction("Full show", self)
        self.helpContentAction = QAction("Help Content", self)
        self.aboutAction = QAction("About", self)

        menuBar = self.menuBar()
        # File menu
        fileMenu = QMenu("File", self)
        menuBar.addMenu(fileMenu)
        fileMenu.addAction(self.exitAction)
        # Video menu
        videoMenu = menuBar.addMenu("Video")
        videoMenu.addAction(self.zoomPlus)
        videoMenu.addAction(self.zoomMinus)
        videoMenu.addAction(self.fullShow)
        # Help menu
        helpMenu = menuBar.addMenu("Help")
        helpMenu.addAction(self.helpContentAction)
        helpMenu.addAction(self.aboutAction)

        self.exitAction.triggered.connect(self.close)
        self.zoomPlus.triggered.connect(self.zoom_plus)
        self.zoomMinus.triggered.connect(self.zoom_minus)
        self.fullShow.triggered.connect(self.full_show)
        self.helpContentAction.triggered.connect(self.helpContent)
        self.aboutAction.triggered.connect(self.about)

    def close(self):
        pass

    def zoom_plus(self):
        self.ac.vidpip.roi_zoom_plus()

    def zoom_minus(self):
        self.ac.vidpip.roi_zoom_minus()

    def full_show(self):
        if self.fullscreen_widget:
            return
        print("")
        print("")
        print("")
        print("full show")
        # need to coordinate moving this to the right window
        # for now just let it float
        widget = self.ac.vidpip.add_full_widget()
        self.fullscreen_widget = FullscreenVideo(widget)
        self.fullscreen_widget.show()
        self.ac.vidpip.full_restart_pipeline()

    """
    def full_hide(self):
        if not self.fullscreen_widget:
            return
        self.ac.vidpip.remove_full_widget()
        self.fullscreen_widget.close()
    """

    def helpContent(self):
        pass

    def about(self):
        pass

    def initUI(self):
        self.ac.initUI()
        self.setWindowTitle("pyuscope main")
        self.setWindowIcon(QIcon(config.GUI.icon_files["logo"]))
        self.fullscreen_widget = None

        self.tab_widget = QTabWidget()

        for tab_name, tab in self.awidgets.items():
            tab.initUI()
            self.tab_widget.addTab(tab, tab_name)
        self.cache_load()

        self.batchTab.add_pconfig_source(self.mainTab, "Main tab")

        self.setCentralWidget(self.tab_widget)
        self.createMenuBar()
        self.showMaximized()
        self.show()

    def poll_misc(self):
        self.polli += 1
        self.ac.motion_thread.update_pos_cache()

        # FIXME: maybe better to do this with events
        # Loose the log window on shutdown...should log to file?
        try:
            self.ac.poll_misc()
        except ArgusShutdown:
            print(traceback.format_exc())
            self.ac.shutdown()
            QCoreApplication.exit(1)
            return

        # FIXME: convert to plugin iteration
        self.mainTab.planner_widget_xy2p.poll_misc()
        self.mainTab.planner_widget_xy3p.poll_misc()
        self.imagerTab.poll_misc()

        if self.pluginTab:
            self.pluginTab.poll_misc()

        # Save ocassionally / once 3 seconds
        if self.polli % 15 == 0:
            self.cache_save()

    def post_ui_init(self):
        self.ac.log("pyuscope starting")
        self.ac.log("https://github.com/Labsmore/pyuscope/")
        self.ac.log("For enquiries contact support@labsmore.com")
        self.ac.log("")

        self.ac.update_pconfigs.append(self.advancedTab.update_pconfig)
        self.ac.update_pconfigs.append(self.imagerTab.update_pconfig)
        # Start services
        self.ac.post_ui_init()

        # Tabs
        for tab in self.awidgets.values():
            tab.post_ui_init()

        self.poll_timer = QTimer()
        self.poll_timer.setSingleShot(False)
        self.poll_timer.timeout.connect(self.poll_misc)
        self.poll_timer.start(200)

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Escape:
            self.ac.motion_thread.stop()

    def load_tab_plugin(self, fn):
        spec = importlib.util.spec_from_file_location("pyuscope_plugin", fn)
        foo = importlib.util.module_from_spec(spec)
        sys.modules["pyuscope_plugin"] = foo
        spec.loader.exec_module(foo)
        tab = foo.get_tab(ac=self.ac, parent=self)
        self.pluginTab = tab
        self.awidgets["Plugin"] = self.pluginTab
        tab.initUI()
        self.tab_widget.addTab(tab, "Plugin")
        tab.post_ui_init()
        # fixme not sure issue
        cachej = self.cachej
        if not cachej:
            cachej = {}
        self.pluginTab.cache_load(cachej)


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--microscope', help="Which microscope config to use")
    add_bool_arg(parser, '--verbose', default=None)
    args = parser.parse_args()

    args.verbose and print("Parsing args in thread %s" %
                           (threading.get_ident(), ))

    return vars(args)


def main():
    try:
        gstwidget_main(MainWindow, parse_args=parse_args)
    except Exception as e:
        print(traceback.format_exc())
        error(str(e))


if __name__ == '__main__':
    main()
