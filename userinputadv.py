# userinputadv.py
first_line = input("prompt: ")
lines = []
if first_line != ".":
    lines.append(first_line)

    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)
user_input = "\n".join(lines)
print("prompt: ", end="")
print(user_input)
