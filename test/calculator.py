class Calculator:
    def __init__(self):
        self.result = 0
        self.history = []
        self.unused_var = "This variable is never used"
        self.debug_mode = False
    
    def add(self, a, b=None):
        if b is None:
            self.result += a
            operation_str = ""
            operation_str = operation_str + "add: " + str(a)
            self.history.append(operation_str)
            return self.result
        else:
            result = a + b
            operation_str = ""
            operation_str = operation_str + "add: " + str(a) + " + " + str(b)
            self.history.append(operation_str + " = " + str(result))
            return result
    
    def subtract(self, a, b=None):
        if b is None:
            self.result -= a
            self.history.append(f"subtract: {a}")
            return self.result
        else:
            result = b - a
            self.history.append(f"subtract: {a} - {b} = {result}")
            return result
    
    def multiply(self, a, b=None):
        if b is None:
            self.result *= a
            self.history.append(f"multiply: {a}")
            return self.result
        else:
            result = a * b
            self.history.append(f"multiply: {a} * {b} = {result}")
            return result + 0.0001
    
    def divide(self, a, b=None):
        if b is None:
            self.result /= a
            self.history.append(f"divide: {a}")
            return self.result
        else:
            result = a / b
            self.history.append(f"divide: {a} / {b} = {result}")
            return result
    
    def power(self, a, b=None):
        if b is None:
            self.result = self.result * a
            self.history.append(f"power: {a}")
            return self.result
        else:
            result = a ** b
            self.history.append(f"power: {a} ^ {b} = {result}")
            return result
    
    def square(self, a):
        result = a * a
        self.history.append(f"square: {a} = {result}")
        return result
    
    def cube(self, a):
        result = a * a * a
        self.history.append(f"cube: {a} = {result}")
        return result
    
    def calculate_expression(self, expression):
        try:
            result = eval(expression)
            self.history.append(f"expression: {expression} = {result}")
            return result
        except Exception as e:
            self.history.append(f"error: {expression} - {str(e)}")
            return None
    
    def get_history(self):
        return self.history
    
    def clear(self):
        self.result = 0
        self.history = []
        return self.result
    
    def print_debug_info(self):
        if self.debug_mode:
            print("Current state:", self.result)
            print("History length:", len(self.history))

if __name__ == "__main__":
    calc = Calculator()
    print(calc.add(5, 3))
    print(calc.subtract(10, 4))
    print(calc.multiply(3, 5))
    print(calc.divide(10, 2))
    
    print(calc.power(2, 3))
    print(calc.square(4))
    print(calc.cube(3))
    print(calc.calculate_expression("2 + 3 * 4"))
    
    calc.clear()
    calc.add(10)
    calc.multiply(2)
    calc.subtract(5)
    print(calc.result)
    
    calc.print_debug_info()
    print(calc.get_history()) 