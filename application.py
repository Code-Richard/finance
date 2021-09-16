import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from pytz import timezone

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    ID = session['user_id']

    # Collects info on all stocks held by user
    stock_info = db.execute("SELECT symbol, SUM(number_of_shares) FROM stocks WHERE user_id = ? GROUP BY symbol", ID)

   # Finds current prices for all stocks held by user and sets total number of shares according to holdings table
    current_prices = {}
    to_remove = []

    # Removes stocks that are no longer owned
    holdings = db.execute("SELECT symbol FROM holdings WHERE user_id = ?", ID)
    holdings_list = [a_dict['symbol'] for a_dict in holdings]
    print(holdings_list)
    
    for stock in stock_info:
        if stock['symbol'] not in holdings_list:
            to_remove.append(stock['symbol'])

    for i in range(len(to_remove)):
        for j in range(len(stock_info)):
            if to_remove[i] == stock_info[j]['symbol']:
                del stock_info[j]
                break

    # Updates number of shares according to holdings db
    for stock in stock_info:
        stock["SUM(number_of_shares)"] = db.execute(
            "SELECT number_of_shares FROM holdings WHERE user_id = ? and symbol = ?", ID, stock['symbol'])[0]['number_of_shares']
        current_prices[stock['symbol']] = lookup(stock['symbol'])['price']

    # Finds the updated value of user portfolio (not including cash)
    total_amount = 0
    total_value_per_stock = {}
    for stock in current_prices:
        no_of_shares = db.execute("SELECT number_of_shares FROM holdings WHERE user_id = ? AND symbol = ?", ID, stock)[
            0]['number_of_shares']
        total_value_per_stock[stock] = no_of_shares * current_prices[stock]
        total_amount += no_of_shares * current_prices[stock]

    # Calculates cash amount held by user
    user_cash = round(db.execute("SELECT cash FROM users WHERE id = ?", ID)[0]["cash"], 2)

    # Calculates the total value of user's portfolio
    total = total_amount + user_cash
    
    # Calculates % return    
    pc_return = round((total - 10000) / 100, 2)
    return render_template("index.html", stock_info=stock_info, total=total, pc_return=pc_return, user_cash=user_cash, current_prices=current_prices, total_value_per_stock=total_value_per_stock)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    ID = session['user_id']
    if request.method == "POST":
        """Buy shares of stock"""
        symbol = request.form.get("symbol").upper()

        # Checks stock exists
        if lookup(symbol) != None:
            price_per_share = lookup(symbol)["price"]
            try:
                shares = int(request.form.get("shares"))
                if shares <= 0:
                    return apology("Enter a positive integer!")
            except:
                return apology("Enter a positive integer!")
            cash_needed = shares * price_per_share

            user_cash = db.execute("SELECT cash FROM users WHERE id = ?", ID)[0]["cash"]

            # Checks which stocks are currently being held
            current_holdings = set()
            stocks_held = db.execute("SELECT symbol FROM stocks WHERE user_id = ?", ID)
            for stock in stocks_held:
                current_holdings.add(stock['symbol'])
            
            print(current_holdings)
            # Checks user has enough cash and updates cash
            if cash_needed <= user_cash:
                user_cash -= cash_needed
                time = datetime.now(timezone('UTC')).strftime("%x %X")
                db.execute("UPDATE users SET cash = ? WHERE id = ?", user_cash, ID)
                db.execute("INSERT INTO stocks (user_id, symbol, price, number_of_shares, total_amount, time, action) VALUES (?, ?, ?, ?, ?, ?, 'BUY')",
                           ID, symbol, price_per_share, shares, cash_needed, time)

                try:
                    # Updates holding db if user already owns the stock
                    if symbol in current_holdings:
                        no_of_shares = db.execute("SELECT SUM(number_of_shares) FROM stocks WHERE user_id = ? AND symbol = ?", ID, symbol)[
                            0]['SUM(number_of_shares)']
                        db.execute("UPDATE holdings SET number_of_shares = ? WHERE user_id = ? and symbol = ?", no_of_shares, ID, symbol)
                    # Updates holding db if user does not already own the stock
                    else:
                        db.execute("INSERT INTO holdings (user_id, symbol, number_of_shares) VALUES (?, ?, ?)", ID, symbol, shares)
                # Handles case where user is buying stock for first time (user_id does not exist in stocks table yet) - could JOIN on users table to find ID rather than using "user_id"
                except:
                    db.execute("INSERT INTO holdings (user_id, symbol, number_of_shares) VALUES (?, ?, ?)", ID, symbol, shares)

                return redirect("/")

            else:
                return apology("Sorry, you do not have cash!")

        else:

            return apology(f"{symbol} could not be found!")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    ID = session['user_id']

    stock_info = db.execute("SELECT * FROM stocks WHERE user_id = ?", ID)
    return render_template("history.html", stock_info=stock_info)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        price = lookup(symbol)
        if price == None:
            return apology(f"{symbol} could not be found")
        return render_template("quoted.html", price=price, symbol=symbol)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
#"""Register user"""
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("Username not entered")

        if not password:
            return apology("Password not entered")
        if len(password) < 8 or password.isalpha():
            return apology("Password must be at least 8 characters and contain at least one number")

        if password != confirmation:
            return apology("Passwords do not match")
        
        # Checks if username chosen is available
        taken_usernames = db.execute("SELECT username FROM users")
        taken_usernames_list = [a_dict['username'] for a_dict in taken_usernames]
        if username in taken_usernames_list:
            return apology("Username already taken")

        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, generate_password_hash(password))
        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    ID = session['user_id']
    # Gets stocks owned by the user and stores in list
    user_holdings = db.execute("SELECT symbol FROM holdings WHERE user_id = ?", ID)
    holdings = [a_dict['symbol'] for a_dict in user_holdings]
 
    if request.method == "POST":

        # Collects info about users sell request
        symbol = request.form.get("symbol").upper()
        try:
            shares = int(request.form.get("shares"))
        except:
            return apology("Enter a positive integer!")

        no_of_shares = db.execute("SELECT number_of_shares FROM holdings WHERE user_id = ? AND symbol = ?",
                                  ID, symbol)[0]['number_of_shares']

        # Checks eligibility of transaction
        if symbol in holdings:
            if shares <= no_of_shares and shares > 0:
                current_price = lookup(symbol)['price']
                updated_no_of_shares = no_of_shares - shares
                if updated_no_of_shares == 0:
                    db.execute("DELETE FROM holdings WHERE symbol = ?", symbol)
                else:
                    db.execute("UPDATE holdings SET number_of_shares = ? WHERE symbol = ? AND user_id = ?",
                               updated_no_of_shares, symbol, ID)

                # Updates stocks db
                cash_made = current_price * shares
                time = datetime.now(timezone('UTC')).strftime("%x %X")
                db.execute("INSERT INTO stocks (user_id, symbol, price, number_of_shares, total_amount, time, action) VALUES (?, ?, ?, ?, ?, ?, 'SELL')",
                           ID, symbol, current_price, shares, cash_made, time)

                # Updates user cash
                user_cash = db.execute("SELECT cash FROM users WHERE id = ?", ID)[0]["cash"]
                cash_made = current_price * shares
                user_cash += cash_made
                db.execute("UPDATE users SET cash = ? WHERE id = ?", user_cash, ID)

                return redirect("/")
            else:
                return apology("You don't have that many shares!")
        else:
            return apology("You don't own that stock!")
    else:
        return render_template("sell.html", user_holdings=user_holdings)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
