# SPDX-License-Identifier: LGPL-2.1-or-later
# Kovač — built on FreeCAD (https://www.freecad.org). Not an official FreeCAD product.
import FreeCADGui as Gui


class KovacWorkbench(Gui.Workbench):
    MenuText = "Kovač"
    ToolTip = "Kovač design environment, built on FreeCAD"

    def __init__(self):
        import kovac
        self.__class__.Icon = kovac.icon("app")

    def Initialize(self):
        from kovac import shell
        shell.initialize(self)

    def Activated(self):
        from kovac import commands, shell
        try:
            shell.activated()
        except Exception as e:      # never a blocking "workbench failure" box
            import traceback
            commands.report("Kovač could not finish starting: %s" % e)
            commands.App.Console.PrintError(traceback.format_exc())

    def Deactivated(self):
        from kovac import shell
        shell.deactivated()

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(KovacWorkbench())
