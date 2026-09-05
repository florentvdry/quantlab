import './globals.css'

export const metadata={
  title:'QuantLab · Research OS',
  description:'Quantitative research, validation and Alpaca Paper monitoring',
}

export default function RootLayout({children}){
  return <html lang="fr"><body>{children}</body></html>
}
