def divide(a, b):
    return a / b  # crashes if b=0
def add(a, b):
    return a - b  # wrong operator
def get_user(user_id):
    users = {1: "Alice", 2: "lan"}
    return users[user_id]  # crashes if id not found

