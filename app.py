import tkinter as tk
from tkinter import ttk
import yfinance as yf
import threading
import time

class ArbitrageApp:
    def _init_(self, root):
        self.root = root
        self.root.title("Arbitrage Opportunity Monitor")
        self.root.geometry("400x500")
        
        # --- State Variables ---
        self.symbol = "^NSEI"  # Nifty 50
        self.strike_price = tk.IntVar(value=23500)
        self.spot_val = tk.DoubleVar(value=0.0)
        self.call_val = tk.DoubleVar(value=0.0)
        self.put_val = tk.DoubleVar(value=0.0)
        self.synthetic_val = tk.DoubleVar(value=0.0)
        self.gap_val = tk.DoubleVar(value=0.0)
        
        self.create_widgets()
        
        # Start the background data thread
        self.update_thread = threading.Thread(target=self.data_loop, daemon=True)
        self.update_thread.start()

    def create_widgets(self):
        # Header
        ttk.Label(self.root, text="Market Arbitrage Monitor", font=("Arial", 16, "bold")).pack(pady=10)
        
        # Spot Price Display
        frame_spot = ttk.Frame(self.root)
        frame_spot.pack(pady=5)
        ttk.Label(frame_spot, text="Nifty Spot: ").pack(side="left")
        ttk.Label(frame_spot, textvariable=self.spot_val, foreground="blue", font=("Arial", 12, "bold")).pack(side="left")

        # Strike Price Selector (+ / - Buttons)
        frame_strike = ttk.LabelFrame(self.root, text="Select Strike Price", padding=10)
        frame_strike.pack(pady=10, fill="x", padx=20)
        
        ttk.Button(frame_strike, text="-", command=lambda: self.adjust_strike(-50)).pack(side="left", expand=True)
        ttk.Label(frame_strike, textvariable=self.strike_price, font=("Arial", 14, "bold")).pack(side="left", expand=True)
        ttk.Button(frame_strike, text="+", command=lambda: self.adjust_strike(50)).pack(side="left", expand=True)

        # Data Display Table
        data_frame = ttk.Frame(self.root)
        data_frame.pack(pady=20)

        rows = [
            ("Call Price (CE):", self.call_val),
            ("Put Price (PE):", self.put_val),
            ("Synthetic Price:", self.synthetic_val),
            ("Arbitrage Gap:", self.gap_val)
        ]

        for i, (label_text, var) in enumerate(rows):
            ttk.Label(data_frame, text=label_text, font=("Arial", 10)).grid(row=i, column=0, sticky="w", pady=5, padx=10)
            ttk.Label(data_frame, textvariable=var, font=("Arial", 10, "bold")).grid(row=i, column=1, sticky="e", pady=5)

        # Indicator Light for Arbitrage
        self.status_label = ttk.Label(self.root, text="Scanning Market...", foreground="gray")
        self.status_label.pack(pady=20)

    def adjust_strike(self, amount):
        self.strike_price.set(self.strike_price.get() + amount)
        self.status_label.config(text="Updating for new strike...", foreground="orange")

    def data_loop(self):
        """Background loop to fetch data without freezing the GUI."""
        ticker = yf.Ticker(self.symbol)
        
        while True:
            try:
                # 1. Fetch Spot
                hist = ticker.history(period="1d")
                if not hist.empty:
                    spot = hist['Close'].iloc[-1]
                    self.spot_val.set(round(spot, 2))

                # 2. Get Nearest Expiry and Option Chain
                expiry = ticker.options[0]
                opt = ticker.option_chain(expiry)
                
                # 3. Filter by current UI Strike
                current_strike = self.strike_price.get()
                call_data = opt.calls[opt.calls['strike'] == current_strike]
                put_data = opt.puts[opt.puts['strike'] == current_strike]

                if not call_data.empty and not put_data.empty:
                    c_price = call_data['lastPrice'].values[0]
                    p_price = put_data['lastPrice'].values[0]
                    
                    # 4. Calculation logic (Your original features)
                    # Formula: Synthetic = Strike + CE - PE
                    synthetic = current_strike + c_price - p_price
                    gap = synthetic - spot
                    
                    # 5. Update UI Variables
                    self.call_val.set(c_price)
                    self.put_val.set(p_price)
                    self.synthetic_val.set(round(synthetic, 2))
                    self.gap_val.set(round(gap, 2))
                    
                    # Update Status Color
                    if abs(gap) > 5:
                        self.status_label.config(text="OPPORTUNITY DETECTED", foreground="green")
                    else:
                        self.status_label.config(text="Market Efficient", foreground="gray")

            except Exception as e:
                print(f"Data Fetch Error: {e}")
            
            time.sleep(10) # Refresh rate (yfinance is rate-limited)

if _name_ == "_main_":
    root = tk.Tk()
    app = ArbitrageApp(root)
    root.mainloop()
