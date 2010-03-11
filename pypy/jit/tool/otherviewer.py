#!/usr/bin/env python
""" Usage: otherviewer.py loopfile
"""

import optparse
import sys
import re
import math

import autopath
from pypy.translator.tool.graphpage import GraphPage
from pypy.translator.tool.make_dot import DotGen
from pypy.tool import logparser
from pypy.tool import progressbar

class SubPage(GraphPage):
    def compute(self, graph):
        dotgen = DotGen(str(graph.no))
        dotgen.emit_node(graph.name(), shape="box", label=graph.content)
        self.source = dotgen.generate(target=None)

class Page(GraphPage):
    def compute(self, graphs):
        dotgen = DotGen('trace')
        self.loops = set()
        for graph in graphs:
            graph.grab_loops(self.loops)
        self.links = {}
        self.cache = {}
        for loop in self.loops:
            loop.generate(dotgen)
            loop.getlinks(self.links)
            self.cache["loop" + str(loop.no)] = loop
        self.source = dotgen.generate(target=None)

    def followlink(self, label):
        return SubPage(self.cache[label])

BOX_COLOR = (128, 0, 96)

class BasicBlock(object):
    counter = 0
    startlineno = 0

    def __init__(self, content):
        self.content = content
        self.no = self.counter
        self.__class__.counter += 1

    def name(self):
        return 'node' + str(self.no)

    def getlinks(self, links):
        links[self.linksource] = self.name()

    def generate(self, dotgen):
        dotgen.emit_node(self.name(), label=self.header,
                         shape='box', fillcolor=get_gradient_color(self.ratio))

    def get_content(self):
        return self._content

    def set_content(self, content):
        self._content = content
        groups = re.findall('Guard(\d+)', content)
        if not groups:
            self.first_guard = -1
            self.last_guard = -1
        else:
            self.first_guard = int(groups[0])
            self.last_guard = int(groups[-1])

    content = property(get_content, set_content)

def get_gradient_color(ratio):
    if ratio == 0:
        return 'white'
    ratio = math.log(ratio)      # from -infinity to +infinity
    #
    # ratio: <---------------------- 1.8 --------------------->
    #        <-- towards green ---- YELLOW ---- towards red -->
    #
    ratio -= 1.8
    ratio = math.atan(ratio * 5) / (math.pi/2)
    # now ratio is between -1 and 1
    if ratio >= 0.0:
        # from yellow (ratio=0) to red (ratio=1)
        return '#FF%02X00' % (int((1.0-ratio)*255.5),)
    else:
        # from yellow (ratio=0) to green (ratio=-1)
        return '#%02XFF00' % (int((1.0+ratio)*255.5),)

class FinalBlock(BasicBlock):
    def __init__(self, content, target):
        self.target = target
        BasicBlock.__init__(self, content)

    def postprocess(self, loops, memo):
        postprocess_loop(self.target, loops, memo)

    def grab_loops(self, loops):
        if self in loops:
            return
        loops.add(self)
        if self.target is not None:
            self.target.grab_loops(loops)

    def generate(self, dotgen):
        BasicBlock.generate(self, dotgen)
        if self.target is not None:
            dotgen.emit_edge(self.name(), self.target.name())

class Block(BasicBlock):
    def __init__(self, content, left, right):
        self.left = left
        self.right = right
        BasicBlock.__init__(self, content)

    def postprocess(self, loops, memo):
        postprocess_loop(self.left, loops, memo)
        postprocess_loop(self.right, loops, memo)

    def grab_loops(self, loops):
        if self in loops:
            return
        loops.add(self)
        self.left.grab_loops(loops)
        self.right.grab_loops(loops)

    def generate(self, dotgen):
        BasicBlock.generate(self, dotgen)
        dotgen.emit_edge(self.name(), self.left.name())
        dotgen.emit_edge(self.name(), self.right.name())

def split_one_loop(real_loops, guard_s, guard_content, lineno, no, allloops):
    for i in range(len(allloops) - 1, -1, -1):
        loop = allloops[i]
        if no < loop.first_guard or no > loop.last_guard:
            continue
        content = loop.content
        pos = content.find(guard_s + '>')
        if pos != -1:
            newpos = content.rfind("\n", 0, pos)
            oldpos = content.find("\n", pos)
            assert newpos != -1
            if oldpos == -1:
                oldpos = len(content)
            if isinstance(loop, Block):
                left = Block(content[oldpos:], loop.left, loop.right)
            else:
                left = FinalBlock(content[oldpos:], None)
            right = FinalBlock(guard_content, None)
            mother = Block(content[:oldpos], len(allloops), len(allloops) + 1)
            allloops[i] = mother
            allloops.append(left)
            allloops.append(right)
            if hasattr(loop, 'loop_no'):
                real_loops[loop.loop_no] = mother
                mother.loop_no = loop.loop_no
            mother.guard_s = guard_s
            mother.startlineno = loop.startlineno
            left.startlineno = loop.startlineno + content.count("\n", 0, pos)
            right.startlineno = lineno
            return
    else:
        raise Exception("Did not find")

MAX_LOOPS = 300

def splitloops(loops):
    real_loops = []
    counter = 1
    bar = progressbar.ProgressBar(color='blue')
    single_percent = len(loops) / 100
    allloops = []
    for i, loop in enumerate(loops):
        if i > MAX_LOOPS:
            return real_loops, allloops
        if single_percent and i % single_percent == 0:
            bar.render(i / single_percent)
        firstline = loop[:loop.find("\n")]
        m = re.match('# Loop (\d+)', firstline)
        if m:
            no = int(m.group(1))
            assert len(real_loops) == no
            _loop = FinalBlock(loop, None)
            real_loops.append(_loop)
            _loop.startlineno = counter
            _loop.loop_no = no
            allloops.append(_loop)
        else:
            m = re.search("bridge out of Guard (\d+)", firstline)
            assert m
            guard_s = 'Guard' + m.group(1)
            split_one_loop(real_loops, guard_s, loop, counter,
                           int(m.group(1)), allloops)
        counter += loop.count("\n") + 2
    return real_loops, allloops

def postprocess_loop(loop, loops, memo):
    if loop in memo:
        return
    memo.add(loop)
    if loop is None:
        return
    m = re.search("debug_merge_point\('<code object (.*?)> (.*?)'", loop.content)
    if m is None:
        name = '?'
    else:
        name = m.group(1) + " " + m.group(2)
    opsno = loop.content.count("\n")
    lastline = loop.content[loop.content.rfind("\n", 0, len(loop.content) - 2):]
    m = re.search('descr=<Loop(\d+)', lastline)
    if m is not None:
        assert isinstance(loop, FinalBlock)
        loop.target = loops[int(m.group(1))]
    bcodes = loop.content.count('debug_merge_point')
    loop.linksource = "loop" + str(loop.no)
    loop.header = "%s loop%d\n%d operations\n%d opcodes" % (name, loop.no, opsno,
                                                          bcodes)
    loop.header += "\n" * (opsno / 100)
    if bcodes == 0:
        loop.ratio = opsno
    else:
        loop.ratio = float(opsno) / bcodes
    content = loop.content
    lines = content.split("\n")
    if len(lines) > 100:
        lines = lines[100:] + ["%d more lines..." % (len(lines) - 100)]
    for i, line in enumerate(lines):
        lines[i] = re.sub("\[.*\]", "", line)
    loop.content = "Logfile at %d\n" % loop.startlineno + "\n".join(lines)
    loop.postprocess(loops, memo)

def postprocess(loops, allloops):
    for loop in allloops:
        if isinstance(loop, Block):
            loop.left = allloops[loop.left]
            loop.right = allloops[loop.right]
    memo = set()
    for loop in loops:
        postprocess_loop(loop, loops, memo)

def main(loopfile, view=True):
    log = logparser.parse_log_file(loopfile)
    loops = logparser.extract_category(log, "jit-log-opt-")
    real_loops, allloops = splitloops(loops)
    postprocess(real_loops, allloops)
    if view:
        Page(allloops).display()

if __name__ == '__main__':
    parser = optparse.OptionParser(usage=__doc__)
    options, args = parser.parse_args(sys.argv)
    if len(args) != 2:
        print __doc__
        sys.exit(1)
    main(args[1])
