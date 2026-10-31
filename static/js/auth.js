// สลับการมองเห็นรหัสผ่าน โดยไม่ส่งหรือบันทึกรหัสผ่านเพิ่มเติม
'use strict';
document.querySelectorAll('.password-toggle').forEach(button=>{
  button.addEventListener('click',()=>{
    const input=document.getElementById(button.dataset.target);
    const visible=input.type==='password';
    input.type=visible?'text':'password';
    button.textContent=visible?'ซ่อน':'แสดง';
    button.setAttribute('aria-pressed',String(visible));
  });
});
const phoneOtpButton=document.getElementById('phone-otp-send');
if(phoneOtpButton){phoneOtpButton.addEventListener('click',async()=>{
 const phone=document.querySelector('input[name="phone"]');const status=document.getElementById('phone-otp-status');
 if(!phone.reportValidity())return;
 phoneOtpButton.disabled=true;status.textContent='กำลังตรวจบริการส่ง OTP…';
 try{const token=document.querySelector('input[name="csrf_token"]').value;const response=await fetch('/api/auth/phone-otp/send',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify({phone:phone.value})});const data=await response.json();status.textContent=data.error||'ยังไม่สามารถยืนยันเบอร์มือถือได้';}
 catch(error){status.textContent='เชื่อมต่อบริการ OTP ไม่สำเร็จ กรุณาลองใหม่ภายหลัง';}finally{phoneOtpButton.disabled=false;}
});}
