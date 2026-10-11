# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parameters (ADR-0004): user parameters live in one App::VarSet named "Parameters"; model
parameters are the numeric properties of history features. Both take plain values with
units ("2 in"), or expressions (start with "=", or use parameter names). Giving a model value
a name promotes it: a user parameter is created and the feature is bound to it."""
import FreeCAD as App

from kovac import commands, model

KINDS = {"Length": "App::PropertyLength", "Angle": "App::PropertyAngle", "Number": "App::PropertyFloat",
         "Count": "App::PropertyInteger"}
NUMERIC = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle", "App::PropertyFloat",
           "App::PropertyInteger", "App::PropertyIntegerConstraint", "App::PropertyFloatConstraint", "App::PropertyQuantity")
VARSET = "Parameters"


def varset(doc, create=True):
    v = doc.getObject(VARSET)
    if v is None and create:
        v = doc.addObject("App::VarSet", VARSET)
    return v


def user_params(doc):
    v = varset(doc, create=False)
    if v is None:
        return []
    return [p for p in v.PropertiesList if v.getGroupOfProperty(p) == "Parameters"]


def add_user(doc, name, kind="Length", value=None, comment=""):
    if not name.isidentifier():
        raise ValueError("A parameter name is letters, digits and _ and starts with a letter.")
    v = varset(doc)
    if name in v.PropertiesList:
        raise ValueError("%s already exists." % name)
    v.addProperty(KINDS[kind], name, "Parameters", comment)
    if value is not None:
        set_value(v, name, str(value))
    return v


def remove_user(doc, name):
    users = [(o, p) for o in doc.Objects for p, _e in (o.ExpressionEngine or []) if ("%s.%s" % (VARSET, name)) in _e]
    if users:
        raise ValueError("%s is used by %s." % (name, ", ".join("%s.%s" % (o.Label, p) for o, p in users)))
    varset(doc).removeProperty(name)


def expression(obj, prop):
    return dict(obj.ExpressionEngine or []).get(prop, "")


def set_value(obj, prop, text):
    """'12', '2 in', '=Thickness*2' or 'Thickness*2' -> value or expression."""
    text = str(text).strip()
    if text.startswith("="):
        obj.setExpression(prop, _names(obj.Document, text[1:]))
        return
    try:
        q = App.Units.Quantity(text)
    except Exception:
        obj.setExpression(prop, _names(obj.Document, text))    # a formula or a parameter name
        return
    obj.setExpression(prop, None)
    cur = getattr(obj, prop)
    if isinstance(cur, int):
        setattr(obj, prop, int(round(q.Value)))
    elif isinstance(cur, float):
        setattr(obj, prop, q.Value)
    else:
        setattr(obj, prop, q)            # quantity property: '2 in' becomes 50.8 mm


def _names(doc, expr):
    """User parameter names may be written bare; the expression engine needs Parameters.<name>."""
    for name in user_params(doc):
        expr = _qualify(expr, name)
    return expr


def _qualify(expr, name):
    import re
    return re.sub(r"(?<![\w.])%s(?![\w(])" % re.escape(name), "%s.%s" % (VARSET, name), expr)


def model_params(doc):
    """[(feature, property)] for numeric properties of history features, in history order."""
    out = []
    for o in model.items(doc):
        if not model.is_feature(o):
            continue
        for p in o.PropertiesList:
            if o.getTypeIdOfProperty(p) in NUMERIC and "Hidden" not in o.getPropertyStatus(p) and o.getGroupOfProperty(p) not in ("Kovac", "Base"):
                out.append((o, p))
    return out


def promote(feature, prop, name):
    """Name a model value: make it a user parameter and bind the feature to it."""
    kind = {"App::PropertyAngle": "Angle", "App::PropertyFloat": "Number", "App::PropertyInteger": "Count",
            "App::PropertyIntegerConstraint": "Count"}.get(feature.getTypeIdOfProperty(prop), "Length")
    v = getattr(feature, prop)
    add_user(feature.Document, name, kind, v.UserString if hasattr(v, "UserString") else v)
    feature.setExpression(prop, "%s.%s" % (VARSET, name))


def describe(obj, prop):
    v = getattr(obj, prop)
    return v.UserString if hasattr(v, "UserString") else str(v)


# ---------------------------------------------------------------- dialog

def dialog():
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    import kovac
    from kovac import panel

    def favs():
        return [x for x in kovac.prefs().GetString("FavParams", "").split(",") if x]

    class Params(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("kovacParams")
            lay = QtWidgets.QVBoxLayout(self)
            top = QtWidgets.QHBoxLayout()
            self.search = QtWidgets.QLineEdit(placeholderText="Search parameters…")
            self.only_favs = QtWidgets.QCheckBox("★ only")
            top.addWidget(self.search, 1)
            top.addWidget(self.only_favs)
            lay.addLayout(top)
            lay.addWidget(QtWidgets.QLabel("User parameters", objectName="kovacMuted"))
            self.user = QtWidgets.QTableWidget(0, 4)
            self.user.setHorizontalHeaderLabels(["Name", "Value or expression", "Kind", "Comment"])
            self.user.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.user)
            row = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add")
            rem = QtWidgets.QPushButton("Remove")
            row.addWidget(add)
            row.addWidget(rem)
            row.addStretch()
            lay.addLayout(row)
            lay.addWidget(QtWidgets.QLabel("Model parameters  (double-click a name cell to name it)", objectName="kovacMuted"))
            self.model = QtWidgets.QTreeWidget()
            self.model.setHeaderLabels(["★", "Parameter", "Value or expression"])
            self.model.setColumnWidth(0, 28)
            self.model.setColumnWidth(1, 170)
            lay.addWidget(self.model, 1)
            add.clicked.connect(self.add)
            rem.clicked.connect(self.remove)
            self.search.textChanged.connect(lambda _t: self.refresh())
            self.only_favs.toggled.connect(lambda _b: self.refresh())
            self.user.itemChanged.connect(self.user_edited)
            self.model.itemChanged.connect(self.model_edited)
            self.model.itemDoubleClicked.connect(self.model_clicked)
            self.refresh()

        def doc(self):
            return App.ActiveDocument

        def match(self, *texts):
            q = self.search.text().lower()
            return not q or any(q in t.lower() for t in texts)

        def refresh(self):
            doc = self.doc()
            self._busy = True
            self.user.setRowCount(0)
            self.model.clear()
            if doc is None:
                self._busy = False
                return
            v = varset(doc, create=False)
            fv = favs()
            for name in user_params(doc):
                if (self.only_favs.isChecked() and "user:" + name not in fv) or not self.match(name):
                    continue
                r = self.user.rowCount()
                self.user.insertRow(r)
                expr = expression(v, name)
                cells = [name, "=" + expr if expr else describe(v, name),
                         {b: a for a, b in KINDS.items()}.get(v.getTypeIdOfProperty(name), ""), v.getDocumentationOfProperty(name)]
                for c, text in enumerate(cells):
                    it = QtWidgets.QTableWidgetItem(text)
                    if c in (0, 2):
                        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    it.setData(QtCore.Qt.UserRole, name)
                    self.user.setItem(r, c, it)
            groups = {}
            for o, p in model_params(doc):
                key = "%s.%s" % (o.Name, p)
                if (self.only_favs.isChecked() and key not in fv) or not self.match(o.Label, p):
                    continue
                g = groups.get(o.Name)
                if g is None:
                    g = groups[o.Name] = QtWidgets.QTreeWidgetItem(self.model, ["", o.Label, ""])
                    g.setExpanded(True)
                expr = expression(o, p)
                it = QtWidgets.QTreeWidgetItem(g, ["★" if key in fv else "☆", p, ("=" + expr) if expr else describe(o, p)])
                it.setData(0, QtCore.Qt.UserRole, key)
                it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
            self._busy = False

        def regenerate(self, what, fn):
            try:
                with commands.transaction(what, self.doc()):
                    fn()
                    model.commit(self.doc())
            except Exception as e:
                commands.report(e)
            self.refresh()

        def add(self):
            name, ok = QtWidgets.QInputDialog.getText(self, "New parameter", "Name:", text="Param%d" % (len(user_params(self.doc())) + 1))
            if ok and name:
                self.regenerate("Add parameter", lambda: add_user(self.doc(), name, "Length", "10 mm"))

        def remove(self):
            it = self.user.currentItem()
            if it is not None:
                self.regenerate("Remove parameter", lambda: remove_user(self.doc(), it.data(QtCore.Qt.UserRole)))

        def user_edited(self, it):
            if self._busy:
                return
            name = it.data(QtCore.Qt.UserRole)
            v = varset(self.doc())
            if it.column() == 1:
                self.regenerate("Set " + name, lambda: set_value(v, name, it.text()))
            elif it.column() == 3:
                v.setDocumentationOfProperty(name, it.text())

        def model_edited(self, it, col):
            if self._busy or col != 2 or not it.data(0, QtCore.Qt.UserRole):
                return
            oname, prop = it.data(0, QtCore.Qt.UserRole).split(".", 1)
            obj = self.doc().getObject(oname)
            self.regenerate("Set %s.%s" % (obj.Label, prop), lambda: set_value(obj, prop, it.text(2)))

        def model_clicked(self, it, col):
            key = it.data(0, QtCore.Qt.UserRole)
            if not key:
                return
            if col == 0:
                fv = favs()
                kovac.prefs().SetString("FavParams", ",".join([f for f in fv if f != key] if key in fv else fv + [key]))
                self.refresh()
            elif col == 1:
                oname, prop = key.split(".", 1)
                obj = self.doc().getObject(oname)
                name, ok = QtWidgets.QInputDialog.getText(self, "Name this value", "Parameter name:", text=prop)
                if ok and name:
                    self.regenerate("Name parameter", lambda: promote(obj, prop, name))

    d = panel.show("Params", "Parameters", Params)
    d.widget().refresh()
    return d


def register():
    import kovac
    commands.add("Kovac_Parameters", "Parameters", "User and model parameters, with units and expressions", dialog,
                 icon=kovac.icon("parameters"), active=commands.has_doc)
