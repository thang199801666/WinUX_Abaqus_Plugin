"""Composition API tests: no graphical backend required."""
import unittest
from DearUIQt.ribbon.components import RibbonTab, RibbonGroup, RibbonButton, RibbonMenuButton, RibbonSplitButton

class FakeBar:
    def __init__(self):
        self.calls=[]
    def __getattr__(self, method):
        def record(*args, **kwargs):
            self.calls.append((method,args,kwargs))
            if method.startswith(('set_', 'is_')): return True
            return len(self.calls)
        return record

class RibbonCompositionTest(unittest.TestCase):
    def test_hierarchy_and_routing(self):
        bar=FakeBar()
        tab=RibbonTab(bar,'home',100)
        group=tab.add_group('editing','Editing',width=210)
        button=group.add_button('copy','Copy',size='small',image='copy.png')
        menu=group.add_menu_button('layout','Layout',entries=[])
        split=group.add_split_button('paste','Paste',lambda: None,entries=[])
        self.assertIsInstance(group,RibbonGroup)
        self.assertIsInstance(button,RibbonButton)
        self.assertIsInstance(menu,RibbonMenuButton)
        self.assertIsInstance(split,RibbonSplitButton)
        self.assertEqual(len(tab.groups),1)
        self.assertEqual(len(group.commands),3)
        self.assertEqual(bar.calls[1][1][:4],('home','editing','copy','Copy'))
        self.assertTrue(button.set_enabled(False))
        self.assertEqual(bar.calls[-1][1],('copy',False))
        self.assertTrue(tab.activate())
        self.assertTrue(group.set_visible(False))

if __name__ == '__main__': unittest.main()
