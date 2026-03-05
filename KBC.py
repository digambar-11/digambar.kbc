import os
import time

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

questions = [
    {"Q": "Who is known as the 'Father of the Nation' in India?",
        "O1": "A) Jawaharlal Nehru","O2": "B) Mahatma Gandhi", "O3": "C) Subhash Chandra Bose", "O4": "D) Sardar Patel",
        "A": "B", "Hint": "He was first addressed as 'Mahatma' (Great Soul) by Rabindranath Tagore in 1915."},
    {"Q": "In which year did India gain Independence from British rule?",
        "O1": "A) 1942","O2": "B) 1945","O3": "C) 1947","O4": "D) 1950",
        "A": "C", "Hint": "\'Jana Gana Mana\' was originally composed in Bengali before being translated to Hindi."},
    {"Q": "Who was the first Prime Minister of independent India?",
        "O1": "A) Lal Bahadur Shastri","O2": "B) Dr. Rajendra Prasad","O3": "C) Jawaharlal Nehru","O4": "D) Gulzarilal Nanda",
        "A": "C", "Hint": "The first rocket launched by India in 1963 was so small it was transported on a bicycle!"},
    {"Q": "The 'Taj Mahal' was built by which Mughal Emperor?",
        "O1": "A) Akbar","O2": "B) Humayun","O3": "C) Shah Jahan","O4": "D) Aurangzeb",
        "A": "C", "Hint": "It took approximately 22 years and 22,000 workers to complete this marble marvel."},
    {"Q": "Which movement was started by Mahatma Gandhi with the Salt March in 1930?",
        "O1": "A) Non-Cooperation Movement","O2": "B) Civil Disobedience Movement","O3": "C) Quit India Movement","O4": "D) Swadeshi Movement",
        "A": "B", "Hint": "This movement aimed to \"disobey\" British laws peacefully."},
    {"Q": "Who was the first woman Prime Minister of India?",
        "O1": "A) Sarojini Naidu","O2": "B) Indira Gandhi","O3": "C) Pratibha Patil","O4": "D) Sucheta Kripalani",
        "A": "B", "Hint": "She was the daughter of India's first Prime Minister, Jawaharlal Nehru."},
    {"Q": "In which city did the Jallianwala Bagh massacre take place in 1919?",
        "O1": "A) Amritsar","O2": "B) Lahore","O3": "C) Delhi","O4": "D) Meerut",
        "A": "A", "Hint": "This city is also home to the famous Golden Temple."},
    {"Q": "Who is popularly known as the 'Iron Man of India'?",
        "O1": "A) Bhagat Singh","O2": "B) Bal Gangadhar Tilak","O3": "C) Sardar Vallabhbhai Patel","O4": "D) Chandra Shekhar Azad",
        "A": "C", "Hint": "His massive \"Statue of Unity\" is currently the tallest in the world." },
    {"Q": "The 'Revolt of 1857' officially started in which Indian city?",
        "O1": "A) Jhansi","O2": "B) Meerut","O3": "C) Kanpur","O4": "D) Lucknow",
        "A": "B", "Hint": "This city is located in Uttar Pradesh, between Delhi and Muzaffarnagar."},
    {"Q": "Who was the Chairman of the Drafting Committee of the Indian Constitution?",
        "O1": "A) Mahatma Gandhi","O2": "B) Dr. B.R. Ambedkar","O3": "C) Sardar Patel","O4": "D) Dr. S. Radhakrishnan",
        "A": "B", "Hint": "He is also known as the \"Father of the Indian Constitution.\""}
]

def key_val():
    total_money = 0
    count = 1

    clear()
    print("\n" + "="*40)
    print("           Welcome to KBC           ")
    print("="*40)
    print("\n**Point to be noted**.\n1.There are total 10 questions.\n2.Each question has 4 options to choose.\n3.You will earn INR 1000 on each question if you answered correctly.\n4.If you give a wrong answer, you must quit the game and leave with the amount you have won.\n...Best of Luck...")
    input("\nPress Enter to Start the Game...")

    for q in questions:
        clear() 
        print("*" * 45)
        print(f"   QUESTION {count} | Winning Amount : INR {total_money} ")
        print("*" * 45)

        if count == 4:
           print("\nYou are doing Great!!!")
        if count == 6:
           print("\nAwesome!!! You are so smart!")
        if count == len(questions):
           print("\n---This is the last question for 10000 INR---")
        
        print(f"\n{q['Q']}")
        print("\n".join([q['O1'], q['O2'], q['O3'], q['O4']])) 
        
        ans = input("\nYour Answer(For Hint press \"H\" or to Quit press \"Q\") : ").upper()
        
        if ans == q["A"]:
            total_money += 1000
            count += 1
            print(f"\n!!Congratulations!! Your answer is correct and you won INR {total_money}!")
            time.sleep(1) 
        elif ans == "Q":
            confirm = input(f"Are you sure want to quit? You have {total_money} INR till now\nPress \"Y\" to quit or \"N\" to continue : ").upper()
            if confirm == "Y":
                if count == 1:
                    print("Oops!! You lost, Better Luck Next time!")
                else:
                    print(f"Congratulation!! You won {total_money} INR.")
                break 

        elif ans == "H":
            print("\n💡 Hint : ", q["Hint"])
            make_sure = input("Your Answer Please : ").upper()
            if make_sure == q["A"]:
                print(f"\n!!Congratulations!! Your answer is correct and you won INR {total_money}!")
                time.sleep(2)
            elif make_sure == "Q":
                confirm = input(f"Are you sure want to quit? You have {total_money} INR till now\nPress \"Y\" to quit or \"N\" to continue : ").upper()
                if confirm == "Y":
                  if count == 1:
                    print("Oops!! You lost, Better Luck Next time!")
                  else:
                    print(f"Congratulation!! You won {total_money} INR.")
                  break 
            else:
                print(f"\nOops!! Wrong answer\nThe correct answer is {q['A']}.\nYou have to quit with {total_money} INR.")
                return
        
        else:
            print(f"\nOops!! Wrong answer\nThe correct answer is {q['A']}.\nYou have to quit with {total_money} INR.")
            return

    if count > len(questions):
        clear()
        print("\n" + "*"*40)
        print("    UNBELIEVABLE! YOU ARE A WINNER!    ")
        print(f"      TOTAL PRIZE: INR {total_money}      ")
        print("*"*40)

key_val()
