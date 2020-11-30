import datetime

from babel.numbers import format_currency, get_currency_symbol
from pycoingecko import CoinGeckoAPI
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)
from telegram import Update
from datetime import timedelta
from apscheduler.schedulers.background import BackgroundScheduler

import configparser
import logging

# Config
config = configparser.ConfigParser()
config.read("config.ini")

LOGGING_FILENAME = config["GENERAL"]["logging_filename"]

TOKEN = config["TELEGRAM"]["token"]

CURRENCY = config["GENERAL"]["currency"]

# Filelogging
# logging.basicConfig(filename=LOGGING_FILENAME, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#                     level=logging.INFO)
# Screenlogging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

cg = CoinGeckoAPI()


class UserData:
    def __init__(self, user_id):
        self.user_id = user_id
        self.down = 0
        self.up = 0


users = {}


class Bitcoin:
    def __init__(self):
        self.price = 0
        self.timestamp = datetime.datetime.now()
        self.check_price()

    def get_price_formatted(self):
        return format_currency(self.price, CURRENCY.upper(), locale="de_DE")

    def check_price(self):
        print("check price!")
        old_price = self.price
        self.price = cg.get_price(ids="bitcoin", vs_currencies=CURRENCY.lower())[
            "bitcoin"
        ][CURRENCY.lower()]
        log_msg = f"Old Price: {old_price} - New Price: {self.price}"
        logging.debug(log_msg)
        self.timestamp = datetime.datetime.now()

    def get_timestamp(self):
        format = "%d.%m.%Y %H:%M:%S"
        return self.timestamp.strftime(format)


class BcAlert:
    def __init__(self, token, price_check_seconds=60, message_intervall=10):
        print("... init")
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        self.dispatcher.add_handler(
            CommandHandler("start", self.start, pass_job_queue=True)
        )
        self.dispatcher.add_handler(CommandHandler("help", self.start))
        self.dispatcher.add_handler(CommandHandler("now", self.get_actual_price))
        self.dispatcher.add_handler(
            CommandHandler("set", self.set_alarm, pass_job_queue=True)
        )
        self.dispatcher.add_handler(CommandHandler("unset", self.unset))
        self.dispatcher.add_handler(CommandHandler("down", self.set_limit_down))
        self.dispatcher.add_handler(CommandHandler("up", self.set_limit_up))
        self.dispatcher.add_handler(CommandHandler("amount", self.set_amount))
        self.dispatcher.add_handler(
            MessageHandler(Filters.text & ~Filters.command, self.echo)
        )
        self.dispatcher.add_handler(CommandHandler("info", self.info))

        self.bc = Bitcoin()

        # Scheduler for checking the Price every minute
        self.scheduler = BackgroundScheduler()
        # self.scheduler.start()

        job_time = datetime.datetime.now() + timedelta(seconds=5)
        self.jobs = []
        self.jobs.append(
            self.scheduler.add_job(
                self.bc.check_price,
                "interval",
                next_run_time=job_time,
                seconds=price_check_seconds,
                max_instances=1,
            )
        )
        print("# Starting start_polling()")
        logging.info("# Starting start_polling()")
        self.updater.start_polling()

        self.msg_interval = message_intervall  # Seconds

    def start(self, update: Update, context: CallbackContext) -> None:
        log_msg = f"Message from {update.message.from_user.name}: {update.message.text}"
        logging.debug(log_msg)
        update.message.reply_text("/info für infos eingeben.")

    def remove_job_if_exists(self, name, context):
        """Remove job with given name. Returns whether job was removed."""
        current_jobs = context.job_queue.get_jobs_by_name(name)
        if not current_jobs:
            return False
        for job in current_jobs:
            job.schedule_removal()
        return True

    def set_alarm(self, update, context: CallbackContext) -> None:
        """Add a job to the queue."""
        chat_id = update.message.chat_id

        if not self.scheduler.running:
            self.scheduler.start()

        self.remove_job_if_exists(str(chat_id), context)
        user_context = [update.message.chat_id, update.message.from_user.name]
        if not chat_id in users.keys():
            users[chat_id] = UserData(chat_id)
        context.job_queue.run_repeating(
            self.price_info,
            self.msg_interval,
            1,
            context=user_context,
            name=str(update.message.chat_id),
        )
        logging.debug(f"Pricecheck set for: {update.message.from_user.name}")
        text = "Pricecheck gesetzt."
        update.message.reply_text(text)

    def unset(self, update: Update, context: CallbackContext) -> None:
        """Remove the job if the user changed their mind."""
        chat_id = update.message.chat_id

        job_removed = self.remove_job_if_exists(str(chat_id), context)
        if len(context.job_queue.jobs()) > 0:
            print(context.job_queue.jobs()[0])
        else:
            print("Kein weiterer Job vorhanden! Stoppe Kursabfrage.")
            self.scheduler.pause()
        text = "Pricecheck gestoppt!" if job_removed else "Pricecheck wasn't set."
        debug_msg = f"Alarm unset for: {update.message.from_user.name}"
        logging.debug(debug_msg)
        print(debug_msg)
        update.message.reply_text(text)

    def price_info(self, context: CallbackContext):
        # Get BC-Price from CoinGecko
        # self.bc.check_price()
        # print("BC-Preis: ", self.bc.get_price_formatted())
        logging.debug(f"Getting price_info for: {context.job.context[1]}")
        user_id = context.job.context[0]
        if user_id in users.keys():
            user = users[user_id]
            if user.down == 0 or user.up == 0:
                msg = f"Bitcoinpreis: {self.bc.get_price_formatted()}"
            else:
                if self.bc.price < user.down:
                    msg = f"Bitcoinpreis unter Limit: {self.bc.get_price_formatted()}"
                elif self.bc.price > user.up:
                    msg = f"Bitcoinpreis über Limit: {self.bc.get_price_formatted()}"
                else:
                    return
            if hasattr(users[user_id], "amount"):
                value = users[user_id].amount * self.bc.price
                print("Portfolio-Wert: ", value)
                msg += f"\nPortfolio-Wert: {format_currency(value, CURRENCY.upper(), locale='de_DE')}"
            msg += f"\nAktualisiert: {self.bc.get_timestamp()}"
        else:
            users[user_id] = UserData(user_id)
            msg = f"Bitcoinpreis: {self.bc.get_price_formatted()}"
            if user_id in users.keys():
                if hasattr(users[user_id], "amount"):
                    value = users[user_id].amount * self.bc.price
                    print("Portfolio-Wert: ", value)
                    msg += f"\nPortfolio-Wert: {format_currency(value, CURRENCY.upper(), locale='de_DE')}"
            msg += f"\nAktualisiert: {self.bc.get_timestamp()}"
        context.bot.send_message(chat_id=user_id, text=msg)
        print("   Message gesendet.")

    def set_limit_down(self, update, context):
        user_id = update.message.chat_id
        if not user_id in users.keys():
            try:
                users[user_id] = UserData(context.job.context[0])
            except:
                msg = "Fehler. Schon /set geschickt?"
        else:
            if len(update.message.text.split()) == 2:
                limit = update.message.text.split()[1]
                if get_currency_symbol(CURRENCY) in limit:
                    if users[user_id].amount:
                        down_limit = int(limit.replace(get_currency_symbol(CURRENCY),""))/users[user_id].amount
                    print("Umgerechnet: ",down_limit)
                else:
                    down_limit = int(limit)
                users[user_id].down = down_limit
                if users[user_id].down == 0:
                    msg = "Down-Limit gelöscht."
                else:
                    msg = f"Neues Down-Limit: {format_currency(users[user_id].down, CURRENCY.upper(), locale='de_DE')}"
            else:
                msg = f"Aktuelles Down-Limit: {format_currency(users[user_id].down, CURRENCY.upper(), locale='de_DE')}"
        logging.info(f"Price limit down for {user_id}: {msg}")
        update.message.reply_text(msg)

    def set_limit_up(self, update, context):
        user_id = update.message.chat_id
        if not user_id in users.keys():
            try:
                users[user_id] = UserData(context.job.context[0])
            except:
                msg = "Fehler. Schon /set geschickt?"
        else:
            if len(update.message.text.split()) == 2:
                limit = update.message.text.split()[1]
                if get_currency_symbol(CURRENCY) in limit:
                    if users[user_id].amount:
                        up_limit = int(limit.replace(get_currency_symbol(CURRENCY),""))/users[user_id].amount
                    print("Umgerechnet: ",up_limit)
                else:
                    up_limit = int(limit)
                users[user_id].up = up_limit
                if users[user_id].up == 0:
                    msg = "Up-Limit gelöscht."
                else:
                    msg = f"Neues Up-Limit: {format_currency(users[user_id].up, CURRENCY.upper(), locale='de_DE')}"
            else:
                msg = f"Aktuelles Up-Limit: {format_currency(users[user_id].up, CURRENCY.upper(), locale='de_DE')}"
        logging.info(f"Price limit up for {user_id}: {msg}")
        update.message.reply_text(msg)

    def set_amount(self, update, context):
        user_id = update.message.chat_id
        if not user_id in users.keys():
            try:
                users[user_id] = UserData(context.job.context[0])
            except:
                msg = "Fehler. Schon /set geschickt?"
        else:
            if len(update.message.text.split()) == 2:
                users[user_id].amount = float(update.message.text.split()[1])
                msg = f"Neue BitCoin-Anzahl: {users[user_id].amount}"
            else:
                if hasattr(users[user_id], "amount") == False:
                    msg = "Anzahl noch nicht gesetzt."
                else:
                    msg = f"Aktuelle BitCoin-Anzahl: {users[user_id].amount}"
        logging.info(f"BitCoin-Amount for {user_id}: {msg}")
        update.message.reply_text(msg)

    def echo(self, update, context):
        print("Message: ", update.message.text)
        logging.info(update.message.text)
        update.message.reply_text(update.message.text)

    def get_actual_price(self, update, context):
        user_id = update.message.chat_id
        msg = f"Bitcoinpreis: {self.bc.get_price_formatted()}"
        if user_id in users.keys():
            if hasattr(users[user_id], "amount"):
                value = users[user_id].amount * self.bc.price
                print("Portfolio-Wert: ", value)
                msg += f"\nPortfolio-Wert: {format_currency(value, CURRENCY.upper(), locale='de_DE')}"
        logging.info(f"{user_id}: {msg}")
        update.message.reply_text(msg)

    def info(self, update, context):
        msg = """
Dieser Bot schickt in regelmäßigen Abständen den aktuellen Bitcoinkurs.
Steuerung über:
/set - starten
/unset - stoppen
/down <zahl> - unteres Limit setzen, ab dem der Kurs geschickt werden soll. Mit /up <zahl>€ kann das Limit in der Währung angegeben weden.
/up <zahl> - oberes Limit setzen, ab dem der Kurs geschickt werden soll. Mit /down <zahl>€ kann das Limit in der Währung angegeben weden.
/now - aktuellen Kurs schicken
/amount <zahl> - Anzahl an BitCoins setzen. Beispiel: 0.004"""
        update.message.reply_text(msg)


def main():
    BcAlert(TOKEN)


if __name__ == "__main__":
    main()
