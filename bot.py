import discord
from discord.ext import commands, tasks
import sqlite3
import random
from datetime import datetime, timedelta

# ===== НАСТРОЙКИ =====
TOKEN = os.getenv'DISCORD TOKEN'  # Вставь сюда токен бота
PREFIX = '!'               # Префикс команд
PASSIVE_INCOME_INTERVAL = 3600  # Интервал дохода: 3600 секунд = 1 час

# Включаем интенты
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ===== БАЗА ДАННЫХ =====
conn = sqlite3.connect('economy.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    last_steal TEXT,
    steal_wins INTEGER DEFAULT 0,
    steal_losses INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS businesses (
    user_id INTEGER PRIMARY KEY,
    business_name TEXT DEFAULT 'Нет бизнеса',
    business_price INTEGER DEFAULT 0,
    business_income INTEGER DEFAULT 0,
    last_income_time TEXT
)
''')
conn.commit()

# ===== ФУНКЦИИ =====

def get_balance(user_id):
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute('INSERT INTO users (user_id, balance) VALUES (?, ?)', (user_id, 1000))
        conn.commit()
        return 1000
    return result[0]

def update_balance(user_id, amount):
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def get_business(user_id):
    cursor.execute('SELECT business_name, business_price, business_income FROM businesses WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is None:
        return None, 0, 0
    return result

def set_business(user_id, name, price, income):
    cursor.execute('''
    INSERT OR REPLACE INTO businesses (user_id, business_name, business_price, business_income, last_income_time)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, name, price, income, datetime.now().isoformat()))
    conn.commit()

def get_last_income_time(user_id):
    cursor.execute('SELECT last_income_time FROM businesses WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        return datetime.fromisoformat(result[0])
    return None

def update_last_income_time(user_id):
    cursor.execute('UPDATE businesses SET last_income_time = ? WHERE user_id = ?', 
                   (datetime.now().isoformat(), user_id))
    conn.commit()

def get_steal_stats(user_id):
    cursor.execute('SELECT steal_wins, steal_losses FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        return result[0], result[1]
    return 0, 0

def update_steal_stats(user_id, won):
    if won:
        cursor.execute('UPDATE users SET steal_wins = steal_wins + 1 WHERE user_id = ?', (user_id,))
    else:
        cursor.execute('UPDATE users SET steal_losses = steal_losses + 1 WHERE user_id = ?', (user_id,))
    conn.commit()

# ===== СОБЫТИЯ =====
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    await bot.change_presence(activity=discord.Game(name="!help | 💰 Экономика"))
    check_income.start()

# ===== ФОНОВАЯ ЗАДАЧА (ДОХОД КАЖДЫЙ ЧАС) =====
@tasks.loop(seconds=60)
async def check_income():
    current_time = datetime.now()
    
    cursor.execute('SELECT user_id, business_name, business_price, business_income, last_income_time FROM businesses')
    businesses = cursor.fetchall()
    
    for user_id, business_name, business_price, business_income, last_income_time_str in businesses:
        if business_price == 0:
            continue
            
        last_time = datetime.fromisoformat(last_income_time_str) if last_income_time_str else current_time
        
        if (current_time - last_time).total_seconds() >= PASSIVE_INCOME_INTERVAL:
            income = int(business_price * 0.1)
            update_balance(user_id, income)
            update_last_income_time(user_id)
            
            try:
                user = await bot.fetch_user(user_id)
                await user.send(f"🏭 *{business_name}* принёс тебе *{income}* монет (10% от цены бизнеса)!")
            except:
                pass

# ===== КОМАНДЫ =====

@bot.command(name='balance', aliases=['bal', 'деньги'])
async def balance(ctx, member: discord.Member = None):
    target = member or ctx.author
    balance = get_balance(target.id)
    business = get_business(target.id)
    
    embed = discord.Embed(
        title=f"💰 Баланс {target.display_name}",
        description=f"На счету: *{balance}* монет",
        color=discord.Color.gold()
    )
    
    if business[0] and business[1] > 0:
        embed.add_field(name="🏭 Бизнес", value=f"{business[0]} (Цена: {business[1]} монет)", inline=False)
        embed.add_field(name="📈 Доход в час", value=f"{int(business[1] * 0.1)} монет", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='steal', aliases=['украсть'])
async def steal(ctx, member: discord.Member):
    """Украсть монеты у другого игрока — !steal @пользователь"""
    
    if member == ctx.author:
        await ctx.send("❌ Нельзя украсть у самого себя!")
        return
    
    if member.bot:
        await ctx.send("❌ Нельзя воровать у бота!")
        return
    
    thief_balance = get_balance(ctx.author.id)
    victim_balance = get_balance(member.id)
    
    if victim_balance < 50:
        await ctx.send(f"❌ У {member.display_name} слишком мало монет для кражи!")
        return
    
    # Шанс на успех: 40% (можно менять)
    success = random.random() < 0.4
    
    if success:
        # Крадём от 5% до 20% от суммы жертвы
        stolen_percent = random.uniform(0.05, 0.20)
        stolen_amount = int(victim_balance * stolen_percent)
        stolen_amount = min(stolen_amount, 5000)  # Максимум 5000 за раз
        
        update_balance(ctx.author.id, stolen_amount)
        update_balance(member.id, -stolen_amount)
        update_steal_stats(ctx.author.id, True)
        
        await ctx.send(f"🔪 *УСПЕХ!* {ctx.author.mention} украл у {member.mention} *{stolen_amount}* монет!")
    else:
        # При провале теряешь от 10 до 100 монет
        penalty = random.randint(10, 100)
        penalty = min(penalty, thief_balance)
        
        update_balance(ctx.author.id, -penalty)
        update_steal_stats(ctx.author.id, False)
        
        await ctx.send(f"💀 *ПРОВАЛ!* {ctx.author.mention} попался и заплатил штраф *{penalty}* монет!")

@bot.command(name='work', aliases=['работа'])
async def work(ctx):
    earnings = random.randint(50, 500)
    update_balance(ctx.author.id, earnings)
    
    phrases = [
        f"💼 Ты поработал и заработал *{earnings}* монет!",
        f"🏗️ Ты построил сайт и получил *{earnings}* монет!",
        f"📝 Ты написал код и заработал *{earnings}* монет!",
        f"🖌️ Ты нарисовал дизайн и получил *{earnings}* монет!",
        f"🔧 Ты починил баги и заработал *{earnings}* монет!"
    ]
    await ctx.send(random.choice(phrases))

@bot.command(name='give', aliases=['передать'])
async def give(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("❌ Сумма должна быть больше нуля!")
        return
    
    if member == ctx.author:
        await ctx.send("❌ Нельзя передать монеты самому себе!")
        return
    
    sender_balance = get_balance(ctx.author.id)
    
    if sender_balance < amount:
        await ctx.send(f"❌ Недостаточно средств! У тебя {sender_balance} монет")
        return
    
    update_balance(ctx.author.id, -amount)
    update_balance(member.id, amount)
    
    await ctx.send(f"✅ {ctx.author.mention} передал {member.mention} *{amount}* монет!")

@bot.command(name='stats', aliases=['стата'])
async def stats(ctx):
    balance = get_balance(ctx.author.id)
    business = get_business(ctx.author.id)
    wins, losses = get_steal_stats(ctx.author.id)
    total_steals = wins + losses
    winrate = round((wins / total_steals * 100) if total_steals > 0 else 0, 1)
    
    embed = discord.Embed(
        title=f"📊 Статистика {ctx.author.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="💰 Баланс", value=f"{balance} монет", inline=True)
    
    if business[0] and business[1] > 0:
        embed.add_field(name="🏭 Бизнес", value=business[0], inline=True)
        embed.add_field(name="💸 Доход в час", value=f"{int(business[1] * 0.1)} монет", inline=True)
    else:
        embed.add_field(name="🏭 Бизнес", value="Нет бизнеса", inline=True)
    
    embed.add_field(name="🔪 Кражи", value=f"✅ Успешно: {wins}\n❌ Провалов: {losses}\n📊 Винрейт: {winrate}%", inline=False)
    embed.add_field(name="💡 Команды", value="• !work — 50-500 монет\n• !steal @user — украсть\n• !buy [номер] — купить бизнес\n• !shop — магазин", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='shop', aliases=['магазин'])
async def shop(ctx):
    businesses = [
        {"name": "⚰️ Кладбище", "price": 100},
        {"name": "🚽 Туалетная компания", "price": 2000},
        {"name": "🌀 Мультяшная компания", "price": 5000},
        {"name": "📄 Офисная компания", "price": 10000},
        {"name": "🏢 Крутая компания с машинами", "price": 15000},
        {"name": "🥛 Завод молочка", "price": 17000},
        {"name": "🤖 ИИ-компания", "price": 20000},
        {"name": "🎡 Парк развлечений", "price": 25000},
        {"name": "🍬 Завод конфет", "price": 200000},
        {"name": "🦸 Супер мен 2", "price": 2},  # 2 монеты для прикола
    ]
    
    embed = discord.Embed(
        title="🏪 Магазин бизнесов",
        description="Купи бизнес и получай *10% от его цены* каждый час!",
        color=discord.Color.green()
    )
    
    for i, biz in enumerate(businesses, 1):
        embed.add_field(
            name=f"{i}. {biz['name']}",
            value=f"💰 Цена: {biz['price']} монет\n📈 Доход в час: {int(biz['price'] * 0.1)} монет",
            inline=False
        )
    
    embed.set_footer(text="Используй !buy [номер] чтобы купить")
    await ctx.send(embed=embed)

@bot.command(name='buy', aliases=['купить'])
async def buy(ctx, number: int):
    businesses = [
        {"name": "⚰️ Кладбище", "price": 100},
        {"name": "🚽 Туалетная компания", "price": 2000},
        {"name": "🌀 Мультяшная компания", "price": 5000},
        {"name": "📄 Офисная компания", "price": 10000},
        {"name": "🏢 Крутая компания с машинами", "price": 15000},
        {"name": "🥛 Завод молочка", "price": 17000},
        {"name": "🤖 ИИ-компания", "price": 20000},
        {"name": "🎡 Парк развлечений", "price": 25000},
        {"name": "🍬 Завод конфет", "price": 200000},
        {"name": "🦸 Супер мен 2", "price": 2},
    ]
    
    if number < 1 or number > len(businesses):
        await ctx.send(f"❌ Введи номер от 1 до {len(businesses)}! Используй !shop")
        return
    
    biz = businesses[number - 1]
    balance = get_balance(ctx.author.id)
    
    if balance < biz["price"]:
        await ctx.send(f"❌ Не хватает {biz['price'] - balance} монет для покупки {biz['name']}!")
        return
    
    update_balance(ctx.author.id, -biz["price"])
    set_business(ctx.author.id, biz["name"], biz["price"], int(biz["price"] * 0.1))
    
    embed = discord.Embed(
        title="✅ Покупка совершена!",
        description=f"Ты купил *{biz['name']}* за {biz['price']} монет!",
        color=discord.Color.green()
    )
    embed.add_field(name="📈 Доход в час", value=f"{int(biz['price'] * 0.1)} монет", inline=False)
    embed.set_footer(text="Доход будет приходить автоматически в ЛС каждый час!")
    await ctx.send(embed=embed)

@bot.command(name='mybusiness', aliases=['мойбизнес'])
async def mybusiness(ctx):
    business = get_business(ctx.author.id)
    
    if not business[0] or business[1] == 0:
        await ctx.send("❌ У тебя нет бизнеса! Используй !shop чтобы купить.")
        return
    
    name, price, income = business
    last_time = get_last_income_time(ctx.author.id)
    
    embed = discord.Embed(
        title=f"🏭 Твой бизнес: {name}",
        color=discord.Color.purple()
    )
    embed.add_field(name="💰 Стоимость", value=f"{price} монет", inline=True)
    embed.add_field(name="📈 Доход в час", value=f"{income} монет (10%)", inline=True)
    
    if last_time:
        next_income = last_time + timedelta(seconds=PASSIVE_INCOME_INTERVAL)
        if next_income > datetime.now():
            remaining = next_income - datetime.now()
            minutes = remaining.seconds // 60
            embed.add_field(name="⏰ Следующий доход через", value=f"{minutes} минут", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['топ'])
async def leaderboard(ctx):
    cursor.execute('SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10')
    top_users = cursor.fetchall()
    
    embed = discord.Embed(
        title="🏆 Топ-10 богачей сервера",
        color=discord.Color.gold()
    )
    
    for i, (user_id, balance) in enumerate(top_users, 1):
        try:
            user = await bot.fetch_user(user_id)
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"
            embed.add_field(name=f"{medal} {i}. {user.display_name}", value=f"💰 {balance} монет", inline=False)
        except:
            embed.add_field(name=f"{i}. Неизвестный", value=f"💰 {balance} монет", inline=False)
    
    await ctx.send(embed=embed)

# ===== ЗАПУСК =====
if __name__ == "__main__":
    bot.run(TOKEN)