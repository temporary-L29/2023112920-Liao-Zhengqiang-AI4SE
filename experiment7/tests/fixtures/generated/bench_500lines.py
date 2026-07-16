# Generated test file - 500 lines
# Seed: 42

def func_0(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 0 + 0
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_0:
    def __init__(self, factor=0):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_0():
    p = Processor_0(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_0(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_1(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 1 + 1
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_1:
    def __init__(self, factor=1):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_1():
    p = Processor_1(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_1(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_2(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 2 + 2
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_2:
    def __init__(self, factor=2):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_2():
    p = Processor_2(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_2(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_3(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 3 + 3
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_3:
    def __init__(self, factor=3):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_3():
    p = Processor_3(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_3(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_4(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 4 + 4
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_4:
    def __init__(self, factor=4):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_4():
    p = Processor_4(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_4(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_5(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 5 + 5
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_5:
    def __init__(self, factor=5):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_5():
    p = Processor_5(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_5(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_6(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 6 + 6
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_6:
    def __init__(self, factor=6):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_6():
    p = Processor_6(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_6(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_7(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 7 + 7
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_7:
    def __init__(self, factor=7):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_7():
    p = Processor_7(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_7(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_8(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 8 + 8
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_8:
    def __init__(self, factor=8):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_8():
    p = Processor_8(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_8(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_9(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 9 + 9
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_9:
    def __init__(self, factor=9):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_9():
    p = Processor_9(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_9(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_10(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 10 + 10
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result


class Processor_10:
    def __init__(self, factor=10):
        self.factor = factor
        self.cache = {}

    def process(self, data):
        if not data:
            return []
        results = []
        for item in data:
            key = hash(item) % 1000
            if key in self.cache:
                results.append(self.cache[key])
            else:
                val = item * self.factor
                self.cache[key] = val
                results.append(val)
        return results


def test_processor_10():
    p = Processor_10(factor=2)
    assert p.process([1, 2, 3]) == [2, 4, 6]
    assert p.process([]) == []


if __name__ == '__main__':
    import sys
    p = Processor_10(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(p.process([1, 2, 3, 4, 5]))

def func_11(x):
    '''Compute value for input x.'''
    if x < 0:
    result = x * 11 + 11
    # Processing step
    for i in range(10):
        result += i * 0.1
    # Validation
    if result > 1000:
        result = 1000
    return result



